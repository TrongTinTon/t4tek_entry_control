from odoo import api, fields, models
from odoo.exceptions import UserError


class EntryControlSyncPolicy(models.Model):
    _name = 'entry.control.sync.policy'
    _description = 'Entry Control Sync Policy'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    sync_enabled = fields.Boolean(string='Allow Sync', default=True)

    user_group_id = fields.Many2one(
        'entry.control.user.group',
        string='User Group',
        required=True,
        ondelete='cascade',
        index=True,
    )
    device_group_id = fields.Many2one(
        'entry.control.device.group',
        string='Device Group',
        required=True,
        ondelete='cascade',
        index=True,
    )

    sync_user_info = fields.Boolean(string='Sync User Info', default=True)
    sync_card = fields.Boolean(string='Sync Card / Password', default=True)
    sync_fingerprint = fields.Boolean(string='Sync Fingerprint', default=False)
    delete_missing_fingerprints = fields.Boolean(
        string='Delete Missing Fingerprints on Device',
        default=False,
        help='When enabled, Sync All Users removes fingerprint indexes from the physical device if those indexes no longer exist in Odoo. This keeps Odoo as the source of truth.'
    )

    user_count = fields.Integer(string='Users', compute='_compute_counts')
    device_count = fields.Integer(string='Devices', compute='_compute_counts')

    last_sync_state = fields.Selection([
        ('none', 'Not Synced'),
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
        ('disabled', 'Disabled'),
    ], default='none', string='Last Sync State')
    last_sync_at = fields.Datetime(string='Last Sync At')
    last_sync_message = fields.Text(string='Last Sync Message')

    _sql_constraints = [
        ('group_pair_unique', 'unique(user_group_id, device_group_id)', 'This user group is already mapped to this device group.'),
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

    @api.depends('user_group_id.user_ids', 'device_group_id.device_ids')
    def _compute_counts(self):
        for rec in self:
            rec.user_count = len(rec.user_group_id.user_ids.filtered(lambda u: u.enabled and u.sync_enabled))
            rec.device_count = len(rec.device_group_id.device_ids.filtered(lambda d: d.enabled and d.sync_users))

    def action_sync_policy(self):
        messages = []
        notification_type = 'success'
        for rec in self:
            rec._sync_policy(raise_error=True)
            if rec.last_sync_state in ('failed', 'partial'):
                notification_type = 'warning'
            messages.append('%s: %s' % (rec.display_name, rec.last_sync_message or 'Synced.'))
        return self._notification_action('Sync Policy', '; '.join(messages[:5]), notification_type=notification_type, sticky=(notification_type != 'success'))

    def action_enable_policy(self):
        self.write({'sync_enabled': True, 'last_sync_state': 'none'})
        return self._notification_action('Enable Policy', 'Enabled %s sync policy/policies.' % len(self), notification_type='success')

    def action_disable_policy(self):
        self.write({'sync_enabled': False, 'last_sync_state': 'disabled'})
        return self._notification_action('Disable Policy', 'Disabled %s sync policy/policies.' % len(self), notification_type='warning')

    def _get_enabled_users(self):
        self.ensure_one()
        if not self.active or not self.sync_enabled or not self.user_group_id.active or not self.user_group_id.sync_enabled:
            return self.env['entry.control.user'].browse()
        return self.user_group_id.user_ids.filtered(lambda u: u.enabled and u.sync_enabled)

    def _get_enabled_devices(self):
        self.ensure_one()
        if not self.active or not self.sync_enabled or not self.device_group_id.active or not self.device_group_id.sync_enabled:
            return self.env['entry.control.device'].browse()
        return self.device_group_id.device_ids.filtered(lambda d: d.enabled and d.sync_users)

    def _is_user_allowed_on_device(self, user, device):
        self.ensure_one()
        if not self.active or not self.sync_enabled:
            return False
        if not self.user_group_id.active or not self.device_group_id.active:
            return False
        if not self.user_group_id.sync_enabled or not self.device_group_id.sync_enabled:
            return False
        return user in self.user_group_id.user_ids and device in self.device_group_id.device_ids

    @api.model
    def is_user_allowed_on_device(self, user, device):
        if not user or not device:
            return False
        policies = self.sudo().search([
            ('active', '=', True),
            ('sync_enabled', '=', True),
            ('user_group_id.active', '=', True),
            ('user_group_id.sync_enabled', '=', True),
            ('device_group_id.active', '=', True),
            ('device_group_id.sync_enabled', '=', True),
        ])
        for policy in policies:
            if user in policy.user_group_id.user_ids and device in policy.device_group_id.device_ids:
                return True
        return False

    @api.model
    def get_user_device_sync_plan(self, controller=False, devices=False):
        """Return dict keyed by (user_id, device_id) with merged sync options.
        This is the scalable replacement for creating 1 assignment row per user/device.
        """
        Device = self.env['entry.control.device'].sudo()
        if devices:
            scope_devices = devices
        elif controller:
            scope_devices = controller.device_ids.filtered(lambda d: d.enabled and d.sync_users)
        else:
            scope_devices = Device.search([('enabled', '=', True), ('sync_users', '=', True)])

        plan = {}
        if not scope_devices:
            return plan

        policies = self.sudo().search([
            ('active', '=', True),
            ('sync_enabled', '=', True),
            ('user_group_id.active', '=', True),
            ('user_group_id.sync_enabled', '=', True),
            ('device_group_id.active', '=', True),
            ('device_group_id.sync_enabled', '=', True),
        ])
        for policy in policies:
            policy_devices = (policy.device_group_id.device_ids & scope_devices).filtered(lambda d: d.enabled and d.sync_users)
            if not policy_devices:
                continue
            policy_users = policy.user_group_id.user_ids.filtered(lambda u: u.enabled and u.sync_enabled)
            if not policy_users:
                continue
            for device in policy_devices:
                for user in policy_users:
                    key = (user.id, device.id)
                    if key not in plan:
                        plan[key] = {
                            'user': user,
                            'device': device,
                            'sync_user_info': False,
                            'sync_card': False,
                            'sync_fingerprint': False,
                            'delete_missing_fingerprints': False,
                            'policies': self.browse(),
                        }
                    plan[key]['sync_user_info'] = plan[key]['sync_user_info'] or policy.sync_user_info
                    plan[key]['sync_card'] = plan[key]['sync_card'] or policy.sync_card
                    plan[key]['sync_fingerprint'] = plan[key]['sync_fingerprint'] or policy.sync_fingerprint
                    plan[key]['delete_missing_fingerprints'] = plan[key]['delete_missing_fingerprints'] and policy.delete_missing_fingerprints
                    plan[key]['policies'] |= policy
        return plan

    def _sync_policy(self, raise_error=False):
        self.ensure_one()
        plan = self.env['entry.control.sync.policy'].get_user_device_sync_plan(devices=self._get_enabled_devices())
        # Keep only rows created by this policy pair.
        valid_users = self._get_enabled_users()
        valid_devices = self._get_enabled_devices()
        rows = [r for r in plan.values() if r['user'] in valid_users and r['device'] in valid_devices]
        return self._sync_plan_rows(rows, raise_error=raise_error)

    def _sync_plan_rows(self, rows, raise_error=False):
        ok_count = 0
        errors = []
        total = len(rows)
        for row in rows:
            user = row['user']
            device = row['device']
            row_errors = []
            if device.controller_id.state != 'approved':
                row_errors.append('Controller %s is not approved.' % device.controller_id.display_name)
            else:
                if row.get('sync_user_info') or row.get('sync_card'):
                    # Hard default for access control: every synced user must have
                    # one selected time rule. Use Time Zone 1 when missing.
                    default_vals = {}
                    if not user.access_timezone_id:
                        default_vals['access_timezone_id'] = 1
                    if not user.access_group_no:
                        default_vals['access_group_no'] = 1
                    if default_vals:
                        user.write(default_vals)
                    if not device._call_agent_sync_user(user, raise_error=False):
                        row_errors.append(device.last_user_sync_message or 'User sync failed')
                # User-only phase: never execute fingerprint upload/delete unless an
                # explicit developer context is passed. This prevents accidental
                # /api/zk/biometric/fingerprint/* calls while testing user creation.
                if row.get('sync_fingerprint') and self.env.context.get('entry_control_allow_fingerprint_sync'):
                    if not user.with_context(entry_control_allow_fingerprint_sync=True)._sync_fingerprints_to_device(
                        device.with_context(entry_control_allow_fingerprint_sync=True),
                        raise_error=False,
                        delete_missing=False,
                    ):
                        row_errors.append(device.last_biometric_message or 'Fingerprint sync failed')
            if row_errors:
                errors.append('%s → %s: %s' % (user.pin, device.display_name, '; '.join(row_errors)))
            else:
                ok_count += 1
                user._write_sync_result('success', 'Synced by sync policy to %s.' % device.display_name, device)
        if errors:
            msg = 'Synced %s/%s user-device target(s). Errors: %s' % (ok_count, total, '; '.join(errors[:20]))
            if len(errors) > 20:
                msg += ' ... and %s more error(s).' % (len(errors) - 20)
            self.write({
                'last_sync_state': 'partial' if ok_count else 'failed',
                'last_sync_at': fields.Datetime.now(),
                'last_sync_message': msg,
            })
            if raise_error:
                raise UserError(msg)
            return False
        msg = 'Synced %s user-device target(s).' % ok_count
        self.write({
            'last_sync_state': 'success',
            'last_sync_at': fields.Datetime.now(),
            'last_sync_message': msg,
        })
        return True
