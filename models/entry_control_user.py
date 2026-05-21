from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


DEVICE_USER_NAME_MAX_CHARS = 19
DEVICE_USER_NAME_MAX_UTF8_BYTES = 23
DEVICE_USER_NAME_LIMIT_SAMPLE = 'Nguyễn Thị Minh Kha'


class EntryControlUser(models.Model):
    _name = 'entry.control.user'
    _description = 'Entry Control User'
    _order = 'pin, name'

    name = fields.Char(
        string='Full Name',
        required=True,
        size=DEVICE_USER_NAME_MAX_CHARS,
        help='Name sent to the ZKTeco device. Limited to %s characters / %s UTF-8 bytes, tested with sample: %s.'
             % (DEVICE_USER_NAME_MAX_CHARS, DEVICE_USER_NAME_MAX_UTF8_BYTES, DEVICE_USER_NAME_LIMIT_SAMPLE),
    )
    pin = fields.Char(string='User PIN', required=True, index=True)
    password = fields.Char(string='Device Password')
    card_no = fields.Char(string='Card No')

    privilege = fields.Selection([
        ('0', 'Normal User'),
        ('1', 'Registrar'),
        ('2', 'Administrator'),
        ('3', 'Super Administrator'),
    ], string='Privilege', default='0', required=True)

    access_group_no = fields.Integer(
        string='Access Group No',
        default=1,
        help='ZKTeco access-control group number. Default 1.'
    )
    access_timezone_id = fields.Integer(
        string='Access Time Zone ID',
        default=1,
        help='ZKTeco access-control time zone id. Default 1.'
    )

    enabled = fields.Boolean(string='Enabled on Device', default=True)
    sync_enabled = fields.Boolean(string='Allow Sync', default=True)

    # Legacy optional link only. Device Users are global and are not required
    # to belong to a controller or a physical device.
    controller_id = fields.Many2one(
        'entry.control.controller',
        string='Legacy Controller',
        required=False,
        ondelete='set null',
        help='Legacy optional link. Device Users are managed globally; leave empty for the new flow.',
    )
    employee_id = fields.Many2one('hr.employee', string='Linked Employee')
    # Legacy optional link only. The new sync flow uses all global Device Users
    # and targets devices from the selected Controller/Device action.
    device_ids = fields.Many2many(
        'entry.control.device',
        'entry_control_user_device_rel',
        'user_id',
        'device_id',
        string='Legacy Target Devices',
        domain="[('enabled', '=', True)]",
        help='Legacy optional link. Leave empty for the new global Device User flow.'
    )


    biometric_ids = fields.One2many(
        'entry.control.biometric',
        'user_id',
        string='Biometric Templates',
    )

    last_sync_state = fields.Selection([
        ('none', 'Not Synced'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], default='none', string='Last Sync State')
    last_sync_at = fields.Datetime(string='Last Sync At')
    last_sync_message = fields.Text(string='Last Sync Message')
    last_sync_device_id = fields.Many2one('entry.control.device', string='Last Sync Device')

    _sql_constraints = [
        ('pin_unique_global', 'unique(pin)', 'Device User PIN must be unique.'),
    ]

    def _notification_action(self, title, message, notification_type='success', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': sticky,
            },
        }

    @api.model
    def _normalize_device_user_name(self, name):
        """Normalize the display name that is sent to ZKTeco devices.

        The tested SenseFace/ZKTeco device accepts a short display-name buffer.
        The longest Vietnamese sample confirmed by the project is
        "Nguyễn Thị Minh Kha".  That is 19 Unicode characters and
        23 UTF-8 bytes, so we enforce both limits to avoid SDK/device-side
        truncation or rejected sync requests.
        """
        text = str(name or '').strip()

        if len(text) > DEVICE_USER_NAME_MAX_CHARS:
            text = text[:DEVICE_USER_NAME_MAX_CHARS].rstrip()

        while text and len(text.encode('utf-8')) > DEVICE_USER_NAME_MAX_UTF8_BYTES:
            text = text[:-1].rstrip()

        return text

    @api.model
    def _get_default_device_password(self, pin):
        """Default local password sent to the device.

        For generated Device Users, the machine-local password should be
        pre-filled so the user payload is complete on first sync.  We use
        the Employee/User PIN as the default and never overwrite an existing
        manually entered password unless the caller explicitly provides one.
        """
        return str(pin or '').strip()

    @api.model_create_multi
    def create(self, vals_list):
        Employee = self.env['hr.employee'].sudo()
        for vals in vals_list:
            employee = Employee.browse(vals.get('employee_id')).exists() if vals.get('employee_id') else Employee.browse()
            if employee:
                vals['pin'] = self._get_employee_pin_code(employee)
                barcode = str(getattr(employee, 'barcode', False) or '').strip()
                if not vals.get('name'):
                    vals['name'] = employee.name or employee.display_name
                if not vals.get('card_no') and barcode:
                    vals['card_no'] = barcode
            elif vals.get('pin') is not None:
                vals['pin'] = str(vals.get('pin') or '').strip()

            if vals.get('name') is not None:
                vals['name'] = self._normalize_device_user_name(vals.get('name'))

            if not vals.get('password') and vals.get('pin'):
                vals['password'] = self._get_default_device_password(vals.get('pin'))
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        allow_employee_pin_sync = self.env.context.get('entry_control_allow_employee_pin_sync')

        if vals.get('name') is not None:
            vals['name'] = self._normalize_device_user_name(vals.get('name'))

        # For Device Users linked to an employee, User PIN is a reference to
        # hr.employee PIN Code. It must not be edited independently.
        if 'employee_id' in vals:
            employee = self.env['hr.employee'].sudo().browse(vals.get('employee_id')).exists() if vals.get('employee_id') else self.env['hr.employee'].browse()
            if employee:
                vals['pin'] = self._get_employee_pin_code(employee)
            elif vals.get('pin') is not None:
                vals['pin'] = str(vals.get('pin') or '').strip()
        elif vals.get('pin') is not None:
            normalized_pin = str(vals.get('pin') or '').strip()
            linked_records = self.filtered('employee_id')
            if linked_records and not allow_employee_pin_sync:
                blocked = []
                for rec in linked_records:
                    employee_pin = rec._get_employee_pin_code(rec.employee_id)
                    if normalized_pin != employee_pin:
                        blocked.append('%s → Employee PIN Code: %s' % (rec.display_name, employee_pin))
                if blocked:
                    raise UserError(
                        'User PIN is referenced from Employee PIN Code and cannot be edited manually.\n%s'
                        % '\n'.join(blocked[:20])
                    )
            vals['pin'] = normalized_pin

        return super().write(vals)

    @api.constrains('employee_id')
    def _check_unique_employee_id(self):
        for rec in self.filtered('employee_id'):
            duplicate = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    'Each employee can have only one Device User. Employee %s is already linked to PIN %s.'
                    % (rec.employee_id.display_name, duplicate.pin)
                )

    @api.constrains('employee_id', 'pin')
    def _check_pin_matches_employee_pin_code(self):
        for rec in self.filtered('employee_id'):
            employee_pin = rec._get_employee_pin_code(rec.employee_id)
            if str(rec.pin or '').strip() != employee_pin:
                raise ValidationError(
                    'User PIN must reference Employee PIN Code. Employee %s currently has PIN Code %s.'
                    % (rec.employee_id.display_name, employee_pin)
                )

    @api.model
    def _get_employee_pin_code(self, employee):
        if 'pin' not in employee._fields:
            raise UserError('hr.employee does not have field PIN Code (pin). Please install/enable HR Attendance PIN support first.')
        pin = str(employee.pin or '').strip()
        if not pin:
            raise UserError('Employee %s does not have PIN Code. Please fill Employee > HR Settings > PIN Code first.' % employee.display_name)
        return pin

    @api.model
    def action_generate_from_employees(self, *args, **kwargs):
        """Generate global Device Users from existing Employees.

        Rule:
        - employee.pin is the source PIN.
        - one employee can have only one Device User.
        - one PIN can belong to only one Device User.
        - existing Device Users are updated/linked instead of duplicated.
        """
        Employee = self.env['hr.employee'].sudo()
        DeviceUser = self.env['entry.control.user'].sudo()

        if 'pin' not in Employee._fields:
            raise UserError('Employee PIN Code field was not found on hr.employee. Please enable HR Attendance PIN support first.')

        employees = Employee.search([('active', '=', True)], order='name, id')
        employees_with_pin = employees.filtered(lambda emp: bool(str(emp.pin or '').strip()))
        skipped_without_pin = len(employees) - len(employees_with_pin)

        if not employees_with_pin:
            raise UserError('No active employee has PIN Code. Please fill Employee > HR Settings > PIN Code first.')

        pin_to_employees = {}
        for employee in employees_with_pin:
            pin = self._get_employee_pin_code(employee)
            pin_to_employees.setdefault(pin, []).append(employee)

        duplicate_pin_lines = []
        for pin, employee_list in pin_to_employees.items():
            if len(employee_list) > 1:
                names = ', '.join(employee_list[:5].mapped('display_name'))
                if len(employee_list) > 5:
                    names += ', ...'
                duplicate_pin_lines.append('PIN %s: %s' % (pin, names))
        if duplicate_pin_lines:
            raise UserError(
                'Cannot generate Device Users because duplicate Employee PIN Code exists:\n%s'
                % '\n'.join(duplicate_pin_lines[:20])
            )

        existing_for_employees = DeviceUser.search([('employee_id', 'in', employees_with_pin.ids)])
        employee_to_users = {}
        for device_user in existing_for_employees:
            employee_to_users.setdefault(device_user.employee_id.id, DeviceUser.browse())
            employee_to_users[device_user.employee_id.id] |= device_user

        duplicate_employee_lines = []
        for employee_id, user_records in employee_to_users.items():
            if len(user_records) > 1:
                employee = Employee.browse(employee_id)
                duplicate_employee_lines.append(
                    '%s: %s' % (employee.display_name, ', '.join(user_records.mapped('pin')))
                )
        if duplicate_employee_lines:
            raise UserError(
                'Cannot generate Device Users because some employees already have multiple Device Users:\n%s'
                % '\n'.join(duplicate_employee_lines[:20])
            )

        pins = list(pin_to_employees.keys())
        existing_for_pins = DeviceUser.search([('pin', 'in', pins)])
        pin_to_user = {}
        duplicate_device_pin_lines = []
        for device_user in existing_for_pins:
            if device_user.pin in pin_to_user:
                duplicate_device_pin_lines.append(device_user.pin)
            pin_to_user[device_user.pin] = device_user
        if duplicate_device_pin_lines:
            raise UserError(
                'Cannot generate Device Users because duplicate Device User PIN already exists: %s'
                % ', '.join(sorted(set(duplicate_device_pin_lines)))
            )

        conflict_lines = []
        for employee in employees_with_pin:
            pin = self._get_employee_pin_code(employee)
            existing_by_employee = employee_to_users.get(employee.id, DeviceUser.browse())
            existing_by_pin = pin_to_user.get(pin, DeviceUser.browse())
            if existing_by_pin and existing_by_pin.employee_id and existing_by_pin.employee_id.id != employee.id:
                conflict_lines.append(
                    'Employee %s uses PIN %s, but this PIN is already linked to %s.'
                    % (employee.display_name, pin, existing_by_pin.employee_id.display_name)
                )
            if existing_by_employee and existing_by_pin and existing_by_employee.id != existing_by_pin.id:
                conflict_lines.append(
                    'Employee %s already has Device User PIN %s, but Employee PIN Code is %s and belongs to another Device User.'
                    % (employee.display_name, existing_by_employee.pin, pin)
                )
        if conflict_lines:
            raise UserError(
                'Cannot generate Device Users because PIN ownership conflicts were found:\n%s'
                % '\n'.join(conflict_lines[:20])
            )

        created_count = 0
        updated_count = 0
        linked_count = 0

        for employee in employees_with_pin:
            pin = self._get_employee_pin_code(employee)
            barcode = str(getattr(employee, 'barcode', False) or '').strip()
            existing_by_employee = employee_to_users.get(employee.id, DeviceUser.browse())
            existing_by_pin = pin_to_user.get(pin, DeviceUser.browse())

            vals = {
                'name': self._normalize_device_user_name(employee.name or employee.display_name),
                'pin': pin,
                'employee_id': employee.id,
                'enabled': True,
                'sync_enabled': True,
            }
            if barcode:
                vals['card_no'] = barcode

            if existing_by_employee:
                write_vals = dict(vals)
                if not existing_by_employee.password:
                    write_vals['password'] = self._get_default_device_password(pin)
                existing_by_employee.with_context(entry_control_allow_employee_pin_sync=True).write(write_vals)
                updated_count += 1
            elif existing_by_pin:
                write_vals = dict(vals)
                if not existing_by_pin.password:
                    write_vals['password'] = self._get_default_device_password(pin)
                existing_by_pin.with_context(entry_control_allow_employee_pin_sync=True).write(write_vals)
                linked_count += 1
            else:
                vals.update({
                    'password': self._get_default_device_password(pin),
                    'privilege': '0',
                    'access_group_no': 1,
                    'access_timezone_id': 1,
                })
                new_user = DeviceUser.create(vals)
                pin_to_user[pin] = new_user
                created_count += 1

        message = (
            'Generate Device Users completed. Created: %s, Updated: %s, Linked existing PIN: %s, Skipped employees without PIN Code: %s.'
            % (created_count, updated_count, linked_count, skipped_without_pin)
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Generate Device Users',
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                rec.pin = rec._get_employee_pin_code(rec.employee_id)
                rec.name = rec._normalize_device_user_name(rec.employee_id.name)
                barcode = getattr(rec.employee_id, 'barcode', False) or ''
                if not rec.card_no and barcode:
                    rec.card_no = barcode
                if not rec.password and rec.pin:
                    rec.password = rec._get_default_device_password(rec.pin)

    @api.onchange('pin')
    def _onchange_pin_default_password(self):
        for rec in self:
            if rec.pin and not rec.password:
                rec.password = rec._get_default_device_password(rec.pin)

    def action_sync_to_devices(self):
        messages = []
        for rec in self:
            rec._sync_to_devices(raise_error=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_sync_message or 'Synced.'))
        return self._notification_action('Sync to Device(s)', '; '.join(messages[:5]), notification_type='success')

    def action_disable_on_devices(self):
        messages = []
        for rec in self:
            rec.enabled = False
            rec._sync_to_devices(raise_error=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_sync_message or 'Disabled and synced.'))
        return self._notification_action('Disable on Device(s)', '; '.join(messages[:5]), notification_type='warning')

    def action_enable_on_devices(self):
        messages = []
        for rec in self:
            rec.enabled = True
            rec._sync_to_devices(raise_error=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_sync_message or 'Enabled and synced.'))
        return self._notification_action('Enable on Device(s)', '; '.join(messages[:5]), notification_type='success')

    def action_create_fingerprint_index_0(self):
        return self.action_create_fingerprint_indexes()

    def action_create_fingerprint_indexes(self):
        """Create empty fingerprint slots 0-9 for this user.

        This is optional. Pull All Fingerprints can also create records automatically from the device.
        """
        Biometric = self.env['entry.control.biometric']
        created = 0
        skipped = 0
        for rec in self:
            for finger_index in range(10):
                existing = Biometric.search([
                    ('user_id', '=', rec.id),
                    ('biometric_type', '=', 'fingerprint'),
                    ('finger_index', '=', finger_index),
                ], limit=1)
                if existing:
                    skipped += 1
                    continue
                Biometric.create({
                    'user_id': rec.id,
                    'biometric_type': 'fingerprint',
                    'finger_index': finger_index,
                    'algorithm': 'ZKFinger10',
                    'flag': 1,
                })
                created += 1
        return self._notification_action('Create Finger Slots 0-9', 'Created %s slot(s). Existing/skipped: %s.' % (created, skipped), notification_type='success')

    def _get_target_devices(self, devices=None):
        self.ensure_one()
        Device = self.env['entry.control.device'].sudo()
        if devices:
            return devices.filtered(lambda d: d.enabled and d.sync_users)
        if self.device_ids:
            return self.device_ids.filtered(lambda d: d.enabled and d.sync_users)
        return Device.search([('enabled', '=', True), ('sync_users', '=', True)])

    def _sync_to_devices(self, devices=None, raise_error=False):
        self.ensure_one()
        if not self.sync_enabled:
            msg = 'User sync is disabled for this user.'
            self._write_sync_result('failed', msg, False)
            if raise_error:
                raise UserError(msg)
            return False
        devices = self._get_target_devices(devices=devices)
        unapproved_devices = devices.filtered(lambda d: d.controller_id.state != 'approved')
        if unapproved_devices:
            msg = 'Controller is not approved for device(s): %s' % ', '.join(unapproved_devices.mapped('display_name'))
            self._write_sync_result('failed', msg, unapproved_devices[:1])
            if raise_error:
                raise UserError(msg)
            return False
        if not devices:
            msg = 'No enabled target device found.'
            self._write_sync_result('failed', msg, False)
            if raise_error:
                raise UserError(msg)
            return False

        ok_count = 0
        fingerprint_total = 0
        fingerprint_ok = 0
        errors = []

        for device in devices:
            # This is an explicit sync action, not the removed background Auto Connect feature.
            # Connect the selected target device first so the Agent writes to the correct machine,
            # then sync user info and any fingerprint templates already stored in Odoo.
            ok = device._call_agent_sync_user(self, raise_error=False, connect_first=True)
            if not ok:
                errors.append('%s: %s' % (device.display_name, device.last_user_sync_message or 'User sync failed'))
                continue

            ok_count += 1
            biometric_result = self._sync_fingerprints_to_devices(
                devices=device,
                raise_error=False,
                connect_first=False,
            )
            fingerprint_total += biometric_result.get('total', 0)
            fingerprint_ok += biometric_result.get('ok', 0)
            for err in biometric_result.get('errors', []):
                errors.append('%s: %s' % (device.display_name, err))

        if errors:
            msg = 'Synced user info to %s/%s device(s). Fingerprints pushed %s/%s. Errors: %s' % (
                ok_count,
                len(devices),
                fingerprint_ok,
                fingerprint_total,
                '; '.join(errors),
            )
            self._write_sync_result('failed', msg, devices[:1] if devices else False)
            if raise_error:
                raise UserError(msg)
            return False

        if fingerprint_total:
            msg = 'Synced user info to %s device(s). Fingerprints pushed %s/%s.' % (
                ok_count,
                fingerprint_ok,
                fingerprint_total,
            )
        else:
            msg = 'Synced user info to %s device(s). No fingerprint template to push.' % ok_count

        self._write_sync_result('success', msg, devices[:1] if devices else False)
        return True

    def _sync_fingerprints_to_devices(self, devices=None, raise_error=False, connect_first=False):
        self.ensure_one()

        biometrics = self.biometric_ids.filtered(
            lambda b: b.biometric_type == 'fingerprint' and bool(b.template_data)
        ).sorted(key=lambda b: b.finger_index or 0)

        if not biometrics:
            return {'total': 0, 'ok': 0, 'errors': []}

        target_devices = devices or self._get_target_devices()
        target_devices = target_devices.filtered(lambda d: d.enabled and d.sync_users)
        if not target_devices:
            msg = 'No target device found for fingerprint sync.'
            if raise_error:
                raise UserError(msg)
            return {'total': len(biometrics), 'ok': 0, 'errors': [msg]}

        total = 0
        ok_count = 0
        errors = []
        for device in target_devices:
            for biometric in biometrics:
                total += 1
                ok = device._call_agent_upload_fingerprint(
                    biometric,
                    raise_error=False,
                    connect_first=connect_first,
                )
                if ok:
                    ok_count += 1
                else:
                    errors.append('FingerIndex %s: %s' % (
                        biometric.finger_index,
                        device.last_biometric_message or 'Fingerprint upload failed',
                    ))

        if errors and raise_error:
            raise UserError('Fingerprint sync pushed %s/%s template(s). Errors: %s' % (
                ok_count,
                total,
                '; '.join(errors),
            ))

        return {'total': total, 'ok': ok_count, 'errors': errors}

    def _to_agent_payload(self):
        self.ensure_one()
        tz_id = int(self.access_timezone_id or 1)
        group_no = int(self.access_group_no or 1)
        return {
            'pin': self.pin,
            'name': self._normalize_device_user_name(self.name or ''),
            'password': self.password or '',
            'cardNo': self.card_no or '',
            'privilege': int(self.privilege or '0'),
            'enabled': bool(self.enabled),
            # Access-control defaults. Older Controller builds ignore these fields;
            # newer builds use them to ensure the user can verify/open according to TZ/group.
            'applyAccessDefaults': True,
            'groupNo': group_no,
            'timezoneId': tz_id,
            'authorizeTimezoneId': tz_id,
            'authorizeDoorId': 1,
            'userTimezone': '1:1:1:1',
            'ensureFullDayTimezone': True,
            'writeUserAuthorizeTable': True,
        }

    def _write_sync_result(self, state, message, device):
        vals = {
            'last_sync_state': state,
            'last_sync_at': fields.Datetime.now(),
            'last_sync_message': message,
        }
        if device:
            vals['last_sync_device_id'] = device.id
        self.write(vals)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def write(self, vals):
        # Keep generated/linked Device User PIN aligned with Employee PIN Code.
        # A linked Device User cannot have a separate manual PIN.
        if 'pin' in vals and 'pin' in self._fields:
            new_pin = str(vals.get('pin') or '').strip()
            linked_users = self.env['entry.control.user'].sudo().search([('employee_id', 'in', self.ids)])
            if linked_users and not new_pin:
                raise UserError('Cannot clear Employee PIN Code because linked Device User(s) use it as User PIN.')
            if linked_users and new_pin:
                duplicate_user = self.env['entry.control.user'].sudo().search([
                    ('pin', '=', new_pin),
                    ('employee_id', 'not in', self.ids),
                ], limit=1)
                if duplicate_user:
                    raise UserError(
                        'Cannot set Employee PIN Code %s because it is already used by Device User %s.'
                        % (new_pin, duplicate_user.display_name)
                    )

        result = super().write(vals)

        if 'pin' in vals and 'pin' in self._fields:
            DeviceUser = self.env['entry.control.user'].sudo().with_context(entry_control_allow_employee_pin_sync=True)
            for employee in self:
                pin = str(employee.pin or '').strip()
                if not pin:
                    continue
                user = DeviceUser.search([('employee_id', '=', employee.id)], limit=1)
                if user and user.pin != pin:
                    user.write({'pin': pin})

        return result

