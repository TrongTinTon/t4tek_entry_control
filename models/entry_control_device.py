import json
import logging
import time
import uuid
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EntryControlDevice(models.Model):
    _name = 'entry.control.device'
    _description = 'Entry Control Device'
    _order = 'controller_id, sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(
        string='Enabled',
        default=True,
        help='Bật/tắt thiết bị ở mức server. Nếu tắt, Odoo sẽ không sync user xuống thiết bị này.'
    )

    controller_id = fields.Many2one(
        'entry.control.controller',
        string='Controller',
        required=True,
        ondelete='cascade',
    )

    device_code = fields.Char(
        string='Device Code',
        help='Mã nội bộ để phân biệt máy, ví dụ GATE-IN-01.'
    )

    device_ip = fields.Char(string='Device IP', required=True)
    device_port = fields.Integer(string='Device Port', default=4370)
    comm_key = fields.Char(string='Comm Key')
    machine_number = fields.Integer(string='Machine Number', default=1)

    serial_number = fields.Char(string='Serial Number', readonly=True, copy=False)
    platform = fields.Char(string='Platform / Model', readonly=True, copy=False)
    firmware_version = fields.Char(string='Firmware Version', readonly=True, copy=False)
    mac_address = fields.Char(string='MAC Address', readonly=True, copy=False)
    agent_device_endpoint = fields.Char(string='Agent Device Endpoint', readonly=True, copy=False)
    last_diagnostic_at = fields.Datetime(string='Last Diagnostic At', readonly=True, copy=False)
    last_diagnostic_message = fields.Text(string='Last Diagnostic Message', readonly=True, copy=False)


    is_primary = fields.Boolean(
        string='Primary Device',
        help='Thiết bị chính dùng làm mặc định cho các thao tác thủ công như pull fingerprint.'
    )

    sync_users = fields.Boolean(
        string='Allow User Sync',
        default=True,
        help='Nếu tắt, Odoo sẽ không đẩy user xuống thiết bị này.'
    )

    connection_state = fields.Selection([
        ('unknown', 'Unknown'),
        ('connected', 'Connected'),
        ('disconnected', 'Disconnected'),
        ('failed', 'Failed'),
        ('disabled', 'Disabled'),
    ], string='Last Known Device State', default='unknown',
        help='Last known state reported by an explicit connect/status check. This value is not overwritten just because the Controller heartbeat becomes offline.')

    effective_connection_state = fields.Selection([
        ('unknown', 'Unknown'),
        ('connected', 'Connected'),
        ('disconnected', 'Disconnected'),
        ('failed', 'Failed'),
        ('disabled', 'Disabled'),
        ('controller_offline', 'Controller Offline'),
    ], string='Effective Device State', compute='_compute_effective_connection_state')
    controller_runtime_state = fields.Selection([
        ('online', 'Online'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('offline', 'Offline'),
    ], string='Controller Runtime State', compute='_compute_effective_connection_state')
    controller_last_heartbeat_at = fields.Datetime(string='Controller Last Heartbeat', compute='_compute_effective_connection_state')
    effective_connection_message = fields.Char(string='Effective Status Message', compute='_compute_effective_connection_state')

    last_connect_at = fields.Datetime(string='Last Connect At')
    last_connect_message = fields.Text(string='Last Connect Message')

    last_status_at = fields.Datetime(string='Last Status At')
    last_status_message = fields.Text(string='Last Status Message')

    last_user_sync_at = fields.Datetime(string='Last User Sync At')
    last_user_sync_message = fields.Text(string='Last User Sync Message')
    last_user_sync_job_id = fields.Char(string='Last Full Sync Job ID', readonly=True, copy=False)
    last_user_sync_state = fields.Selection([
        ('none', 'None'),
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Last Full Sync State', default='none', readonly=True, copy=False)
    last_user_sync_requested_count = fields.Integer(string='Last Full Sync Requested', readonly=True, copy=False)
    last_user_sync_upserted_count = fields.Integer(string='Last Full Sync Upserted', readonly=True, copy=False)
    last_user_sync_deleted_count = fields.Integer(string='Last Full Sync Deleted', readonly=True, copy=False)
    last_user_sync_failed_count = fields.Integer(string='Last Full Sync Failed', readonly=True, copy=False)
    last_user_sync_total_count = fields.Integer(string='Last Full Sync Total Work', readonly=True, copy=False)
    last_user_sync_processed_count = fields.Integer(string='Last Full Sync Processed Work', readonly=True, copy=False)
    last_user_sync_progress_percent = fields.Integer(string='Last Full Sync Progress', readonly=True, copy=False)
    last_user_sync_current_step = fields.Char(string='Last Full Sync Step', readonly=True, copy=False)
    last_user_sync_current_pin = fields.Char(string='Last Full Sync Current PIN', readonly=True, copy=False)

    last_biometric_at = fields.Datetime(string='Last Biometric At')
    last_biometric_message = fields.Text(string='Last Biometric Message')
    last_fingerprint_pull_job_id = fields.Char(string='Last Fingerprint Pull Job ID', readonly=True, copy=False)
    last_fingerprint_pull_state = fields.Selection([
        ('none', 'None'),
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], string='Last Fingerprint Pull State', default='none', readonly=True, copy=False)
    last_fingerprint_pull_progress_percent = fields.Integer(string='Last Fingerprint Pull Progress', readonly=True, copy=False)
    last_fingerprint_pull_total_users = fields.Integer(string='Last Fingerprint Pull Total Users', readonly=True, copy=False)
    last_fingerprint_pull_processed_users = fields.Integer(string='Last Fingerprint Pull Processed Users', readonly=True, copy=False)
    last_fingerprint_pull_imported_templates = fields.Integer(string='Last Fingerprint Pull Imported Templates', readonly=True, copy=False)
    last_fingerprint_pull_updated_templates = fields.Integer(string='Last Fingerprint Pull Updated Templates', readonly=True, copy=False)
    last_fingerprint_pull_skipped_templates = fields.Integer(string='Last Fingerprint Pull Skipped Templates', readonly=True, copy=False)
    last_fingerprint_pull_failed_users = fields.Integer(string='Last Fingerprint Pull Failed Users', readonly=True, copy=False)
    last_fingerprint_pull_current_step = fields.Char(string='Last Fingerprint Pull Step', readonly=True, copy=False)
    last_fingerprint_pull_current_pin = fields.Char(string='Last Fingerprint Pull Current PIN', readonly=True, copy=False)

    _sql_constraints = [
        (
            'device_code_unique_per_controller',
            'unique(controller_id, device_code)',
            'Device Code must be unique per controller.'
        )
    ]

    @api.depends('enabled', 'connection_state', 'controller_id.last_heartbeat_at', 'controller_id.heartbeat_state')
    def _compute_effective_connection_state(self):
        for rec in self:
            controller_state = rec.controller_id.heartbeat_effective_state if rec.controller_id else 'offline'
            rec.controller_runtime_state = controller_state
            rec.controller_last_heartbeat_at = rec.controller_id.last_heartbeat_at if rec.controller_id else False

            if not rec.enabled or rec.connection_state == 'disabled':
                rec.effective_connection_state = 'disabled'
                rec.effective_connection_message = 'Device is disabled in Odoo.'
            elif controller_state == 'offline':
                rec.effective_connection_state = 'controller_offline'
                rec.effective_connection_message = 'Controller is offline. Device state is unknown; last known state is %s.' % (rec.connection_state or 'unknown')
            else:
                rec.effective_connection_state = rec.connection_state or 'unknown'
                rec.effective_connection_message = 'Controller is %s. Device last known state is %s.' % (controller_state or 'unknown', rec.connection_state or 'unknown')

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


    def _get_or_create_sync_job(self, job_uid, job_type, name=None, payload=None, legacy_model=None, legacy_res_id=None):
        self.ensure_one()
        job_uid = (job_uid or '').strip()
        if not job_uid:
            return False
        SyncJob = self.env['entry.control.sync.job'].sudo()
        job = SyncJob.search([('job_uid', '=', job_uid)], limit=1)
        vals = {
            'name': name or job_uid,
            'job_type': job_type,
            'device_id': self.id,
        }
        if legacy_model:
            vals['legacy_model'] = legacy_model
        if legacy_res_id:
            vals['legacy_res_id'] = legacy_res_id
        if payload is not None:
            try:
                vals['request_payload'] = json.dumps(payload, ensure_ascii=False, indent=2)
            except Exception:
                vals['request_payload'] = str(payload)
        if job:
            job.write(vals)
            return job
        vals.update({
            'job_uid': job_uid,
            'state': 'queued',
            'progress_percent': 0,
            'current_step': 'Queued',
        })
        return SyncJob.create(vals)

    def _apply_sync_job_payload(self, job_uid, job_type, data=None, name=None, payload=None, legacy_model=None, legacy_res_id=None):
        self.ensure_one()
        job = self._get_or_create_sync_job(
            job_uid=job_uid,
            job_type=job_type,
            name=name,
            payload=payload,
            legacy_model=legacy_model,
            legacy_res_id=legacy_res_id,
        )
        if job and isinstance(data, dict):
            job._apply_controller_payload(data, job_type=job_type)
        return job

    def action_view_sync_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sync Jobs',
            'res_model': 'entry.control.sync.job',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
            'context': {'default_device_id': self.id},
        }

    def _normalize_pin_for_match(self, value):
        value = str(value or '').strip()
        if not value:
            return ''
        try:
            return str(int(value))
        except Exception:
            return value

    def _map_fingerprint_algorithm(self, value):
        """Normalize Agent/SDK fingerprint algorithm names to Odoo selection values.

        Important: SenseFace / new architecture devices may expose platform or
        biometric-version strings containing VX13 / 13, but the fingerprint
        template pulled through GetUserTmpExStr is still ZKFinger10.0 when
        ~ZKFPVersion=10. Do not map any value containing 13 to ZKFinger13.
        """
        value = str(value or '').strip()
        upper_value = value.upper().replace(' ', '')

        if not upper_value:
            return 'ZKFinger10'

        if upper_value in ('SSR', 'LEGACY', 'ZKFINGER9', 'ZKFINGER9.0', 'ZKFP9', 'ZKFP9.0'):
            return 'SSR'

        # Old Agent versions returned strings such as:
        # - ZKFinger10/13-Compatible
        # - ZKFinger VX13.0
        # These are not reliable fingerprint algorithm identifiers for this flow.
        # Pull All Fingerprints should store the actual template algorithm as ZKFinger10.
        if 'VX13' in upper_value or '10/13' in upper_value or 'ZKFINGER13' in upper_value:
            return 'ZKFinger10'

        if 'SSR' in upper_value or 'LEGACY' in upper_value:
            return 'SSR'

        return 'ZKFinger10'

    def _find_device_user_by_pin(self, pin):
        self.ensure_one()
        User = self.env['entry.control.user'].sudo()
        raw_pin = str(pin or '').strip()
        if not raw_pin:
            return User.browse()

        device_user = User.search([
            ('pin', '=', raw_pin),
        ], limit=1)
        if device_user:
            return device_user

        normalized_pin = self._normalize_pin_for_match(raw_pin)
        if normalized_pin and normalized_pin != raw_pin:
            device_user = User.search([
                ('pin', '=', normalized_pin),
            ], limit=1)
            if device_user:
                return device_user

        # Last fallback: compare normalized values in Python. This handles cases like 0001 vs 1.
        candidates = User.search([])
        for candidate in candidates:
            if self._normalize_pin_for_match(candidate.pin) == normalized_pin:
                return candidate

        return User.browse()

    def action_enable_device(self):
        self.write({'enabled': True, 'connection_state': 'unknown'})
        return self._notification_action('Enable Device', 'Enabled %s device(s).' % len(self))

    def action_disable_device(self):
        disconnected_primary = 0
        for rec in self:
            rec.write({'enabled': False, 'connection_state': 'disabled'})
            if rec.is_primary:
                rec.controller_id._call_agent_disconnect(raise_error=False)
                disconnected_primary += 1
        message = 'Disabled %s device(s).' % len(self)
        if disconnected_primary:
            message += ' Disconnect command was also sent for %s primary device/controller link(s).' % disconnected_primary
        return self._notification_action('Disable Device', message, notification_type='warning')

    def action_connect_device(self):
        messages = []
        for rec in self:
            rec._call_agent_connect_device(raise_error=True, force_reconnect=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_connect_message or 'Connected.'))
        return self._notification_action('Connect Device', '; '.join(messages[:5]), notification_type='success')

    def action_check_device_status(self):
        messages = []
        for rec in self:
            rec._call_agent_device_status(raise_error=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_status_message or rec.connection_state or 'Status checked.'))
        return self._notification_action('Check Agent Status', '; '.join(messages[:5]), notification_type='success')

    def action_check_full_sync_job_status(self):
        messages = []
        notification_type = 'success'
        for rec in self:
            data = rec._call_agent_full_sync_status(raise_error=True)
            state = data.get('state') if isinstance(data, dict) else rec.last_user_sync_state
            fingerprint_note = ''

            # Safety fallback: when an async full-sync job has completed, pressing
            # Check Full Sync Job also pushes stored fingerprints. This covers
            # older flows where Sync All Users was started asynchronously before
            # this module version was installed.
            if state == 'success':
                users = self.env['entry.control.user'].sudo().search([
                    ('enabled', '=', True),
                    ('sync_enabled', '=', True),
                    ('pin', '!=', False),
                ], order='pin, name')
                fp_result = rec._push_fingerprints_for_users(users, raise_error=False, connect_first=False)
                if fp_result.get('total'):
                    fingerprint_note = ' Fingerprints pushed %s/%s.' % (fp_result.get('ok') or 0, fp_result.get('total') or 0)
                    if fp_result.get('errors'):
                        notification_type = 'warning'
                        fingerprint_note += ' Fingerprint errors: %s' % '; '.join(fp_result.get('errors')[:3])

            if state not in ('success', 'queued', 'running'):
                notification_type = 'warning'
            messages.append(
                '%s: state=%s, progress=%s%%, processed=%s/%s, requested=%s, upserted=%s, deleted=%s, failed=%s. %s%s' % (
                    rec.display_name,
                    state or rec.last_user_sync_state or 'unknown',
                    rec.last_user_sync_progress_percent or 0,
                    rec.last_user_sync_processed_count or 0,
                    rec.last_user_sync_total_count or rec.last_user_sync_requested_count or 0,
                    rec.last_user_sync_requested_count or 0,
                    rec.last_user_sync_upserted_count or 0,
                    rec.last_user_sync_deleted_count or 0,
                    rec.last_user_sync_failed_count or 0,
                    rec.last_user_sync_message or '',
                    fingerprint_note,
                )
            )
        return self._notification_action('Check Full Sync Job', '; '.join(messages[:5]), notification_type=notification_type, sticky=(notification_type != 'success'))

    def action_disconnect_controller(self):
        messages = []
        for rec in self:
            rec.controller_id._call_agent_disconnect(raise_error=True)
            rec._write_connect_result('disconnected', 'Disconnect command sent to controller agent.')
            messages.append('%s: disconnected on server.' % rec.display_name)
        return self._notification_action('Disconnect Controller', '; '.join(messages[:5]), notification_type='success')

    def _write_connect_result(self, state, message=None):
        """Persist the latest device connection result.

        This helper is used by connect/disconnect flows. Without it,
        Odoo raises AttributeError when pressing Connect Device.
        """
        allowed_states = dict(self._fields['connection_state'].selection)
        safe_state = state if state in allowed_states else 'unknown'
        vals = {
            'connection_state': safe_state,
            'last_connect_at': fields.Datetime.now(),
            'last_connect_message': message or '',
        }
        self.write(vals)

    def _write_status_result(self, state, message=None):
        """Persist the latest device status check result."""
        allowed_states = dict(self._fields['connection_state'].selection)
        safe_state = state if state in allowed_states else 'unknown'
        vals = {
            'last_status_at': fields.Datetime.now(),
            'last_status_message': message or '',
        }
        if safe_state in ('connected', 'disconnected', 'failed', 'disabled'):
            vals['connection_state'] = safe_state
        self.write(vals)

    def _write_user_sync_result(self, message=None):
        """Persist the latest user sync result for this device."""
        self.write({
            'last_user_sync_at': fields.Datetime.now(),
            'last_user_sync_message': message or '',
        })

    def _write_full_user_sync_result(self, state=None, message=None, data=None, job_id=None):
        """Persist the latest strict/full user sync state for this physical device."""
        vals = {
            'last_user_sync_at': fields.Datetime.now(),
            'last_user_sync_message': message or '',
        }
        if state:
            vals['last_user_sync_state'] = state
        if job_id:
            vals['last_user_sync_job_id'] = job_id
        if data:
            progress_percent = int(data.get('progressPercent') or 0)
            if state == 'success':
                progress_percent = 100
            elif progress_percent < 0:
                progress_percent = 0
            elif progress_percent > 100:
                progress_percent = 100
            vals.update({
                'last_user_sync_requested_count': int(data.get('requestedCount') or 0),
                'last_user_sync_upserted_count': int(data.get('createdOrUpdatedCount') or 0),
                'last_user_sync_deleted_count': int(data.get('deletedCount') or 0),
                'last_user_sync_failed_count': int(data.get('failedCount') or 0),
                'last_user_sync_total_count': int(data.get('totalCount') or data.get('requestedCount') or 0),
                'last_user_sync_processed_count': int(data.get('processedCount') or 0),
                'last_user_sync_progress_percent': progress_percent,
                'last_user_sync_current_step': data.get('currentStep') or '',
                'last_user_sync_current_pin': data.get('currentPin') or '',
            })
        else:
            if state == 'queued':
                vals['last_user_sync_progress_percent'] = 0
            elif state == 'running':
                vals['last_user_sync_progress_percent'] = max(self.last_user_sync_progress_percent or 0, 1)
            elif state == 'success':
                vals['last_user_sync_progress_percent'] = 100
        self.write(vals)

    def _call_agent_connect_device(self, raise_error=False, force_reconnect=False):
        self.ensure_one()
        controller = self.controller_id

        if not self.enabled:
            msg = 'Device is disabled on server. Skip connect.'
            self._write_connect_result('disabled', msg)
            if raise_error:
                raise UserError(msg)
            return False

        if controller.state != 'approved':
            msg = 'Controller is not approved.'
            self._write_connect_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        base_url = controller.get_agent_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            self._write_connect_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        if force_reconnect:
            controller._call_agent_disconnect(raise_error=False)

        url = base_url + '/api/zk/device/connect'
        payload = {
            'ip': self.device_ip.strip(),
            'port': int(self.device_port or 4370),
            'password': self.comm_key or '',
            'machineNumber': int(self.machine_number or 1),
        }

        try:
            _logger.info(
                '[ENTRY CONTROL] Connect device via Agent. Controller=%s, Device=%s, Url=%s, Payload=%s',
                controller.controller_uid,
                self.device_code or self.name,
                url,
                payload,
            )
            resp = requests.post(
                url,
                headers=controller._get_agent_headers(),
                data=json.dumps(payload),
                timeout=10,
            )
            text = resp.text or ''

            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Agent connect failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_connect_result('failed', msg)
                if raise_error:
                    raise UserError(msg)
                return False

            msg = 'Agent connect OK. Response: %s' % text
            self._write_connect_result('connected', msg)
            return True

        except Exception as ex:
            msg = 'Agent connect exception: %s' % str(ex)
            self._write_connect_result('failed', msg)
            _logger.exception('[ENTRY CONTROL] Agent connect device exception.')
            if raise_error:
                raise UserError(msg)
            return False

    def _call_agent_device_status(self, raise_error=False):
        self.ensure_one()
        controller = self.controller_id
        base_url = controller.get_agent_base_url()

        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            self._write_status_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        url = base_url + '/api/zk/device/status'
        try:
            resp = requests.get(url, headers={'X-API-Key': controller.agent_api_key or 'dev-secret-key'}, timeout=10)
            text = resp.text or ''
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Agent status failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_status_result('failed', msg)
                if raise_error:
                    raise UserError(msg)
                return False

            self._write_status_result('connected', text)
            return True

        except Exception as ex:
            msg = 'Agent status exception: %s' % str(ex)
            self._write_status_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

    def _call_agent_sync_user(self, user, raise_error=False, connect_first=False):
        self.ensure_one()
        if not self.enabled:
            msg = 'Device is disabled. Skip user sync.'
            self._write_user_sync_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        if not self.sync_users:
            msg = 'User sync is disabled for this device.'
            self._write_user_sync_result(msg)
            if raise_error:
                raise UserError(msg)
            return False

        if connect_first:
            connect_ok = self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)
            if not connect_ok:
                return False

        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        url = base_url + '/api/zk/users/sync'
        payload = user._to_agent_payload()

        try:
            _logger.info(
                '[ENTRY CONTROL] Sync user to device. Controller=%s, Device=%s, User=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                user.pin,
                url,
            )
            resp = requests.post(
                url,
                headers=controller._get_agent_headers(),
                data=json.dumps(payload),
                timeout=15,
            )
            text = resp.text or ''
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'User sync failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_user_sync_result(msg)
                user._write_sync_result('failed', msg, self)
                if raise_error:
                    raise UserError(msg)
                return False

            msg = 'User sync OK. Response: %s' % text
            self._write_user_sync_result(msg)
            user._write_sync_result('success', msg, self)
            return True
        except Exception as ex:
            msg = 'User sync exception: %s' % str(ex)
            self._write_user_sync_result(msg)
            user._write_sync_result('failed', msg, self)
            _logger.exception('[ENTRY CONTROL] User sync exception.')
            if raise_error:
                raise UserError(msg)
            return False


    def _build_full_user_sync_payload(self, users, delete_missing=True, preserve_pins=None):
        users = users or self.env['entry.control.user'].browse()
        preserve_pins = preserve_pins or []
        payload_users = []
        for user in users.sorted(key=lambda u: (u.pin or '', u.name or '')):
            if not user.pin:
                continue
            payload = user._to_agent_payload()
            # Compatibility with Controller builds that support access-control defaults.
            if hasattr(user, 'access_group_no') and user.access_group_no:
                payload['groupNo'] = int(user.access_group_no or 1)
            if hasattr(user, 'access_timezone_id') and user.access_timezone_id:
                payload['timezoneId'] = int(user.access_timezone_id or 1)
                payload['authorizeTimezoneId'] = int(user.access_timezone_id or 1)
            payload['applyAccessDefaults'] = True
            payload['ensureFullDayTimezone'] = True
            payload_users.append(payload)
        allow_empty_full_sync = bool(delete_missing) and len(payload_users) == 0
        return {
            'deleteMissing': bool(delete_missing),
            'allowEmptyFullSync': allow_empty_full_sync,
            'preservePins': preserve_pins,
            'users': payload_users,
        }

    def _call_agent_sync_users_full(self, users, delete_missing=True, preserve_pins=None, raise_error=False, connect_first=False, wait=False, sync_fingerprints=False):
        """Start a strict/full device user sync.

        Strict sync means Odoo is the source of truth for the selected device:
        users in the payload are upserted, and device users not present in the
        payload are deleted when delete_missing=True.

        The Controller now supports /api/zk/users/sync-full/start to avoid HTTP
        request timeout for large batches such as 1000 users. If the Controller
        is older and does not support async start, this method falls back to the
        direct /api/zk/users/sync-full endpoint with a larger timeout.
        """
        self.ensure_one()
        users = users or self.env['entry.control.user'].browse()
        users = users.filtered(lambda u: u.enabled and u.sync_enabled and bool(u.pin))
        preserve_pins = preserve_pins or []

        if not self.enabled:
            msg = 'Device is disabled. Skip full user sync.'
            self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
            if raise_error:
                raise UserError(msg)
            return False
        if not self.sync_users:
            msg = 'User sync is disabled for this device.'
            self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
            if raise_error:
                raise UserError(msg)
            return False
        if self.controller_id.state != 'approved':
            msg = 'Controller is not approved.'
            self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
            if raise_error:
                raise UserError(msg)
            return False
        # Empty strict sync is intentionally allowed.
        # Use case: all Device Users were deleted in Odoo and the operator wants
        # to push that empty source-of-truth state to the physical device, so the
        # Agent deletes users that still exist on the device.

        if connect_first:
            connect_ok = self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)
            if not connect_ok:
                return False

        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
            if raise_error:
                raise UserError(msg)
            return False

        payload = self._build_full_user_sync_payload(users, delete_missing=delete_missing, preserve_pins=preserve_pins)

        # Use an Odoo-generated job id so Controller can callback progress immediately,
        # even before the browser user manually refreshes the job status.
        job_id = 'usr-%s-%s' % (self.id, uuid.uuid4().hex[:16])
        odoo_base_url = self._get_odoo_public_base_url()
        payload.update({
            'jobId': job_id,
            'controllerId': controller.controller_uid,
            'controllerToken': controller.api_token or '',
            'odooDatabase': self.env.cr.dbname,
            'deviceId': self.id,
            'deviceCode': self.device_code or self.name or '',
            'deviceIp': self.device_ip or '',
            'devicePort': int(self.device_port or 4370),
            'machineNumber': int(self.machine_number or 1),
        })
        if odoo_base_url:
            payload['callbackProgressUrl'] = odoo_base_url + '/api/entry_control/users/sync/progress'

        self._apply_sync_job_payload(
            job_uid=job_id,
            job_type='user_sync',
            data={
                'jobId': job_id,
                'jobType': 'user_sync',
                'state': 'queued',
                'progressPercent': 0,
                'requestedCount': len(payload.get('users') or []),
                'totalCount': len(payload.get('users') or []),
                'processedCount': 0,
                'currentStep': 'Queued',
                'deviceId': self.id,
                'deviceCode': self.device_code or self.name or '',
            },
            name='Sync All Users - %s' % self.display_name,
            payload=payload,
        )

        async_url = base_url + '/api/zk/users/sync-full/start'
        direct_url = base_url + '/api/zk/users/sync-full'
        headers = controller._get_agent_headers()

        # When called from the Sync All Users button we need a real result, not just
        # an accepted async job. Use the direct endpoint first when wait=True so Odoo
        # can confirm how many users were actually upserted/deleted on the device.
        if wait:
            try:
                estimated_timeout = max(120, min(1800, 20 + len(payload.get('users') or []) * 2))
                _logger.info(
                    '[ENTRY CONTROL] Execute strict full user sync directly. Controller=%s, Device=%s, Users=%s, DeleteMissing=%s, Url=%s, Timeout=%s',
                    controller.controller_uid,
                    self.device_code or self.name,
                    len(payload.get('users') or []),
                    delete_missing,
                    direct_url,
                    estimated_timeout,
                )
                resp = requests.post(direct_url, headers=headers, data=json.dumps(payload), timeout=estimated_timeout)
                text = resp.text or ''
                data = json.loads(text or '{}')
                if resp.status_code >= 200 and resp.status_code < 300 and data.get('success'):
                    msg = 'Strict full user sync completed. Response: %s' % text
                    self._write_full_user_sync_result('success', msg, data)
                    for user in users:
                        user._write_sync_result('success', 'Strict full sync completed on %s.' % self.display_name, self)

                    if sync_fingerprints:
                        fp_result = self._push_fingerprints_for_users(users, raise_error=raise_error, connect_first=False)
                        if fp_result.get('errors') and raise_error:
                            raise UserError('Full user sync completed, but fingerprint push failed: %s' % '; '.join(fp_result.get('errors')[:10]))

                    return True

                # If the Controller does not expose the direct endpoint, fall back to async/start below.
                if resp.status_code != 404:
                    msg = 'Strict full user sync failed. HTTP %s. Response: %s' % (resp.status_code, text)
                    self._write_full_user_sync_result('failed', msg, data)
                    if raise_error:
                        raise UserError(msg)
                    return False

                _logger.warning(
                    '[ENTRY CONTROL] Direct strict full sync endpoint returned 404. Falling back to async start. Url=%s',
                    direct_url,
                )
            except UserError:
                raise
            except Exception as direct_ex:
                msg = 'Strict full user sync direct exception: %s' % str(direct_ex)
                self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
                _logger.exception('[ENTRY CONTROL] Strict full user sync direct exception.')
                if raise_error:
                    raise UserError(msg)
                return False

        try:
            _logger.info(
                '[ENTRY CONTROL] Start strict full user sync. Controller=%s, Device=%s, Users=%s, DeleteMissing=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                len(payload.get('users') or []),
                delete_missing,
                async_url,
            )
            resp = requests.post(async_url, headers=headers, data=json.dumps(payload), timeout=30)
            text = resp.text or ''
            if resp.status_code == 404:
                # Backward compatibility for agents that have only the direct endpoint.
                estimated_timeout = max(120, min(1800, 20 + len(payload.get('users') or []) * 2))
                _logger.warning(
                    '[ENTRY CONTROL] Agent does not support async full sync. Falling back to direct endpoint. Timeout=%s Url=%s',
                    estimated_timeout,
                    direct_url,
                )
                resp = requests.post(direct_url, headers=headers, data=json.dumps(payload), timeout=estimated_timeout)
                text = resp.text or ''
                data = json.loads(text or '{}')
                if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                    msg = 'Strict full user sync failed. HTTP %s. Response: %s' % (resp.status_code, text)
                    self._write_full_user_sync_result('failed', msg, data)
                    if raise_error:
                        raise UserError(msg)
                    return False
                msg = 'Strict full user sync completed by direct endpoint. Response: %s' % text
                self._write_full_user_sync_result('success', msg, data)
                for user in users:
                    user._write_sync_result('success', 'Strict full sync completed on %s.' % self.display_name, self)

                if sync_fingerprints:
                    fp_result = self._push_fingerprints_for_users(users, raise_error=raise_error, connect_first=False)
                    if fp_result.get('errors') and raise_error:
                        raise UserError('Full user sync completed, but fingerprint push failed: %s' % '; '.join(fp_result.get('errors')[:10]))

                return True

            data = json.loads(text or '{}')
            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                msg = 'Start strict full user sync failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_full_user_sync_result('failed', msg, data)
                if raise_error:
                    raise UserError(msg)
                return False

            job_id = data.get('jobId') or ''
            if not job_id:
                msg = 'Start strict full user sync failed: Controller accepted the request but did not return jobId. Response: %s' % text
                self._write_full_user_sync_result('failed', msg, data)
                if raise_error:
                    raise UserError(msg)
                return False

            state = data.get('state') or 'queued'
            msg = 'Strict full user sync job started. Job=%s Users=%s DeleteMissing=%s' % (
                job_id,
                len(payload.get('users') or []),
                delete_missing,
            )
            self._write_full_user_sync_result(state, msg, data, job_id=job_id)
            self._apply_sync_job_payload(
                job_uid=job_id,
                job_type='user_sync',
                data=data,
                name='Sync All Users - %s' % self.display_name,
                payload=payload,
            )

            if wait and job_id:
                wait_ok = self._wait_agent_full_sync_job(job_id, raise_error=raise_error)
                if not wait_ok:
                    return False

                for user in users:
                    user._write_sync_result('success', 'Strict full sync completed on %s. Job=%s' % (self.display_name, job_id), self)

                if sync_fingerprints:
                    fp_result = self._push_fingerprints_for_users(users, raise_error=raise_error, connect_first=False)
                    if fp_result.get('errors') and raise_error:
                        raise UserError('Full user sync completed, but fingerprint push failed: %s' % '; '.join(fp_result.get('errors')[:10]))

                return True

            for user in users:
                user._write_sync_result('success', 'Strict full sync job started for %s. Job=%s' % (self.display_name, job_id), self)

            if sync_fingerprints:
                self._write_biometric_result(
                    'Fingerprint push was requested but skipped because full sync is running asynchronously. '
                    'Use wait=True or check the full sync job status after completion to push fingerprints safely.'
                )

            return True

        except Exception as ex:
            msg = 'Strict full user sync exception: %s' % str(ex)
            self._write_full_user_sync_result('failed', msg, {'requestedCount': len(users)})
            _logger.exception('[ENTRY CONTROL] Strict full user sync exception.')
            if raise_error:
                raise UserError(msg)
            return False

    def _wait_agent_full_sync_job(self, job_id, raise_error=False, poll_interval=3, timeout=1800):
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._call_agent_full_sync_status(job_id=job_id, raise_error=raise_error)
            if not data:
                return False
            state = data.get('state')
            if state in ('success', 'failed'):
                return state == 'success'
            time.sleep(poll_interval)
        msg = 'Strict full user sync job polling timeout. Job=%s' % job_id
        self._write_full_user_sync_result('failed', msg, {'requestedCount': self.last_user_sync_requested_count or 0}, job_id=job_id)
        if raise_error:
            raise UserError(msg)
        return False

    def _push_fingerprints_for_users(self, users, raise_error=False, connect_first=False):
        """Push fingerprint templates for the users after a full user sync.

        Sync All Users rebuilds the user table first. Fingerprints must be pushed
        only after the Agent has finished creating/updating the users; otherwise
        the device may reject SetUserTmpExStr because the PIN does not exist yet.
        """
        self.ensure_one()
        users = users or self.env['entry.control.user'].browse()
        users = users.filtered(lambda u: u.enabled and u.sync_enabled and bool(u.pin))

        if not users:
            msg = 'Fingerprint push skipped: no enabled/sync-enabled Device Users in full sync set.'
            self._write_biometric_result(msg)
            return {'total': 0, 'ok': 0, 'errors': [], 'message': msg}

        biometrics = self.env['entry.control.biometric'].sudo().search([
            ('user_id', 'in', users.ids),
            ('biometric_type', '=', 'fingerprint'),
            ('template_data', '!=', False),
            ('template_data', '!=', ''),
        ], order='user_id, finger_index, id')

        if not biometrics:
            msg = 'Fingerprint push skipped: no stored fingerprint template found for synced users.'
            self._write_biometric_result(msg)
            return {'total': 0, 'ok': 0, 'errors': [], 'message': msg}

        if connect_first:
            connect_ok = self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)
            if not connect_ok:
                msg = 'Fingerprint push aborted: device connect failed.'
                return {'total': len(biometrics), 'ok': 0, 'errors': [msg], 'message': msg}

        job = self._start_fingerprint_push_job(
            biometrics,
            raise_error=raise_error,
            connect_first=False,
        )
        if job:
            errors = []
            if job.state == 'failed':
                errors = [job.last_error or job.message or 'Fingerprint push job failed to start.']
            return {
                'total': len(biometrics),
                'ok': job.success_count or 0,
                'errors': errors,
                'message': job.message or 'Fingerprint push job started.',
                'jobId': job.job_uid,
            }

        # Compatibility fallback for old Controllers that do not yet expose
        # /api/zk/biometric/fingerprint/push/start. New Controllers should use the async job path above.
        bulk_result = self._call_agent_upload_fingerprints_bulk(
            biometrics,
            raise_error=raise_error,
            connect_first=False,
        )
        if bulk_result is not None:
            return bulk_result

        total = len(biometrics)
        ok_count = 0
        errors = []

        for biometric in biometrics:
            ok = self._call_agent_upload_fingerprint(
                biometric,
                raise_error=False,
                connect_first=False,
            )
            if ok:
                ok_count += 1
            else:
                msg = 'PIN %s FingerIndex %s: %s' % (
                    biometric.user_id.pin or '',
                    biometric.finger_index,
                    self.last_biometric_message or biometric.last_sync_message or 'Fingerprint upload failed',
                )
                errors.append(msg)

        if errors:
            message = 'Fingerprint push after full user sync completed with errors. Pushed %s/%s. Errors: %s' % (
                ok_count,
                total,
                '; '.join(errors[:10]),
            )
            if len(errors) > 10:
                message += '; ...'
            self._write_biometric_result(message)
            if raise_error:
                raise UserError(message)
            return {'total': total, 'ok': ok_count, 'errors': errors, 'message': message}

        message = 'Fingerprint push after full user sync OK. Pushed %s/%s template(s).' % (ok_count, total)
        self._write_biometric_result(message)
        return {'total': total, 'ok': ok_count, 'errors': [], 'message': message}

    def _call_agent_full_sync_status(self, job_id=None, raise_error=False):
        self.ensure_one()
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        job_id = job_id or self.last_user_sync_job_id
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            self._write_full_user_sync_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False
        if not job_id:
            msg = 'No full sync job id found for this device.'
            self._write_full_user_sync_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        url = base_url + '/api/zk/users/sync-full/status?jobId=%s' % job_id
        try:
            resp = requests.get(url, headers={'X-API-Key': controller.agent_api_key or 'dev-secret-key'}, timeout=20)
            text = resp.text or ''
            data = json.loads(text or '{}')
            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                msg = 'Full sync job status failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_full_user_sync_result('failed', msg, data, job_id=job_id)
                if raise_error:
                    raise UserError(msg)
                return False

            state = data.get('state') or 'running'
            msg = data.get('message') or 'Full sync job status: %s' % state
            self._write_full_user_sync_result(state, msg, data, job_id=job_id)
            self._apply_sync_job_payload(
                job_uid=job_id,
                job_type='user_sync',
                data=data,
                name='Sync All Users - %s' % self.display_name,
            )
            return data
        except Exception as ex:
            msg = 'Full sync job status exception: %s' % str(ex)
            self._write_full_user_sync_result('failed', msg, job_id=job_id)
            if raise_error:
                raise UserError(msg)
            return False

    def action_push_all_fingerprints(self):
        """Start async push job for all stored fingerprint templates in Odoo."""
        users = self.env['entry.control.user'].sudo().search([
            ('enabled', '=', True),
            ('sync_enabled', '=', True),
            ('pin', '!=', False),
        ], order='pin, name')

        messages = []
        notification_type = 'success'
        for rec in self:
            result = rec._push_fingerprints_for_users(users, raise_error=False, connect_first=False)
            total = result.get('total') or 0
            errors = result.get('errors') or []
            if errors:
                notification_type = 'warning'
            if result.get('jobId'):
                messages.append('%s: Fingerprint push job started. Job=%s Templates=%s%s' % (
                    rec.display_name,
                    result.get('jobId'),
                    total,
                    ('. Errors: %s' % '; '.join(errors[:3])) if errors else '',
                ))
            else:
                messages.append('%s: %s' % (rec.display_name, result.get('message') or 'Fingerprint push not started.'))

        return self._notification_action(
            'Push All Fingerprints',
            '; '.join(messages[:10]),
            notification_type=notification_type,
            sticky=(notification_type != 'success'),
        )

    def action_pull_all_fingerprints(self):
        """Start an async fingerprint pull job.

        Large devices (hundreds/thousands of users) must not return all
        fingerprint templates in one HTTP response. The Controller reads the
        device, splits results into batches, and callbacks each batch to Odoo.
        """
        messages = []
        for rec in self:
            job = rec._start_fingerprint_pull_job(batch_size=50, raise_error=True)
            messages.append('%s: Fingerprint pull job started. Job=%s BatchSize=%s' % (
                rec.display_name, job.job_id, job.batch_size,
            ))
        return self._notification_action('Pull All Fingerprints', '; '.join(messages[:5]), notification_type='success')

    def action_refresh_fingerprint_pull_progress(self):
        messages = []
        notification_type = 'success'
        for rec in self:
            data = rec._call_agent_fingerprint_pull_status(raise_error=True)
            state = (data or {}).get('state') or rec.last_fingerprint_pull_state or ''
            if state in ('failed', 'partial_success'):
                notification_type = 'warning'
            messages.append('%s: %s%% %s' % (
                rec.display_name,
                rec.last_fingerprint_pull_progress_percent or 0,
                rec.last_fingerprint_pull_current_step or state or '',
            ))
        return self._notification_action('Refresh Fingerprint Pull Progress', '; '.join(messages[:5]), notification_type=notification_type)

    def action_retry_fingerprint_pull_job(self):
        messages = []
        for rec in self:
            rec._call_agent_fingerprint_pull_retry(raise_error=True)
            messages.append('%s: retry/resume requested for job %s' % (rec.display_name, rec.last_fingerprint_pull_job_id or ''))
        return self._notification_action('Retry Fingerprint Pull', '; '.join(messages[:5]), notification_type='warning')

    def action_view_fingerprint_pull_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fingerprint Pull Jobs',
            'res_model': 'entry.control.sync.job',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id), ('job_type', '=', 'fingerprint_pull')],
            'context': {'default_device_id': self.id, 'default_job_type': 'fingerprint_pull'},
        }

    def _get_odoo_public_base_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        return base_url.strip().rstrip('/')

    def _write_fingerprint_pull_result(self, state=None, message=None, data=None, job_id=None):
        vals = {
            'last_biometric_at': fields.Datetime.now(),
            'last_biometric_message': message or '',
        }
        if job_id:
            vals['last_fingerprint_pull_job_id'] = job_id
        if state:
            vals['last_fingerprint_pull_state'] = state
        if data:
            def _has(*keys):
                return any(k in data for k in keys)

            def _int_from(keys, default=0):
                for key in keys:
                    if key in data and data.get(key) not in (None, ''):
                        try:
                            return int(data.get(key) or 0)
                        except Exception:
                            return default
                return default

            if _has('progressPercent', 'progress_percent'):
                progress = _int_from(('progressPercent', 'progress_percent'), self.last_fingerprint_pull_progress_percent or 0)
                progress = max(0, min(100, progress))
                if state in ('completed', 'partial_success'):
                    progress = 100
                vals['last_fingerprint_pull_progress_percent'] = progress
            elif state in ('completed', 'partial_success'):
                vals['last_fingerprint_pull_progress_percent'] = 100

            optional_int_map = {
                'last_fingerprint_pull_total_users': ('totalUsers', 'total_users'),
                'last_fingerprint_pull_processed_users': ('processedUsers', 'processed_users'),
                'last_fingerprint_pull_imported_templates': ('importedTemplates', 'imported_templates'),
                'last_fingerprint_pull_updated_templates': ('updatedTemplates', 'updated_templates'),
                'last_fingerprint_pull_skipped_templates': ('skippedTemplates', 'skipped_templates'),
                'last_fingerprint_pull_failed_users': ('failedUsers', 'failed_users'),
            }
            for field_name, keys in optional_int_map.items():
                if _has(*keys):
                    vals[field_name] = _int_from(keys, 0)

            if _has('currentStep', 'current_step'):
                vals['last_fingerprint_pull_current_step'] = data.get('currentStep') or data.get('current_step') or ''
            if _has('currentPin', 'current_pin'):
                vals['last_fingerprint_pull_current_pin'] = data.get('currentPin') or data.get('current_pin') or ''
        self.write(vals)

    def _start_fingerprint_pull_job(self, batch_size=50, raise_error=False):
        self.ensure_one()
        if not self.enabled:
            msg = 'Device is disabled. Cannot start fingerprint pull job.'
            self._write_fingerprint_pull_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False
        if self.controller_id.state != 'approved':
            msg = 'Controller is not approved. Cannot start fingerprint pull job.'
            self._write_fingerprint_pull_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        base_url = self.controller_id.get_agent_base_url()
        odoo_base_url = self._get_odoo_public_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL before pulling fingerprints.'
            self._write_fingerprint_pull_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False
        if not odoo_base_url:
            msg = 'Odoo public base URL is missing. Set web.base.url before using Controller callback.'
            self._write_fingerprint_pull_result('failed', msg)
            if raise_error:
                raise UserError(msg)
            return False

        # Force SDK session to the selected device before starting the background pull.
        if not self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True):
            return False

        job_uuid = uuid.uuid4().hex
        job_id = 'fp-%s-%s' % (self.id, job_uuid[:16])
        job = self.env['entry.control.biometric.pull.job'].sudo().create({
            'name': 'Fingerprint Pull - %s' % self.display_name,
            'job_id': job_id,
            'device_id': self.id,
            'state': 'queued',
            'progress_percent': 0,
            'batch_size': int(batch_size or 50),
            'current_step': 'Queued',
            'message': 'Waiting for Controller to start fingerprint pull.',
        })

        self._apply_sync_job_payload(
            job_uid=job_id,
            job_type='fingerprint_pull',
            data={'jobId': job_id, 'state': 'queued', 'progressPercent': 0, 'batchSize': int(batch_size or 50), 'currentStep': 'Queued'},
            name='Fingerprint Pull - %s' % self.display_name,
            legacy_model=job._name,
            legacy_res_id=job.id,
        )

        payload = {
            'jobId': job_id,
            'controllerId': self.controller_id.controller_uid,
            'controllerToken': self.controller_id.api_token or '',
            'deviceId': self.id,
            'deviceCode': self.device_code or self.name or '',
            'deviceIp': self.device_ip or '',
            'devicePort': int(self.device_port or 4370),
            'machineNumber': int(self.machine_number or 1),
            'password': self.comm_key or '',
            'batchSize': int(batch_size or 50),
            'mode': 'all',
            'callbackBatchUrl': odoo_base_url + '/api/entry_control/biometric/fingerprint/batch',
            'callbackProgressUrl': odoo_base_url + '/api/entry_control/biometric/fingerprint/progress',
            'odooDatabase': self.env.cr.dbname,
        }
        url = base_url + '/api/zk/biometric/fingerprint/pull/start'
        try:
            resp = requests.post(url, headers=self.controller_id._get_agent_headers(), data=json.dumps(payload), timeout=20)
            text = resp.text or ''
            data = json.loads(text or '{}')
            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                msg = 'Start fingerprint pull job failed. HTTP %s. Response: %s' % (resp.status_code, text)
                job.write({'state': 'failed', 'last_error': msg, 'message': msg, 'finished_at': fields.Datetime.now()})
                self._write_fingerprint_pull_result('failed', msg, data, job_id=job_id)
                if raise_error:
                    raise UserError(msg)
                return job

            state = data.get('state') or 'queued'
            msg = data.get('message') or 'Fingerprint pull job started.'
            job._apply_progress_payload(data)
            self._write_fingerprint_pull_result(state, msg, data, job_id=job_id)
            return job
        except Exception as ex:
            msg = 'Start fingerprint pull job exception: %s' % str(ex)
            job.write({'state': 'failed', 'last_error': msg, 'message': msg, 'finished_at': fields.Datetime.now()})
            self._write_fingerprint_pull_result('failed', msg, job_id=job_id)
            _logger.exception('[ENTRY CONTROL] Start fingerprint pull job exception.')
            if raise_error:
                raise UserError(msg)
            return job

    def _call_agent_fingerprint_pull_status(self, job_id=None, raise_error=False):
        self.ensure_one()
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        job_id = job_id or self.last_fingerprint_pull_job_id
        if not base_url or not job_id:
            msg = 'Missing Controller Base URL or fingerprint pull Job ID.'
            self._write_fingerprint_pull_result('failed', msg, job_id=job_id)
            if raise_error:
                raise UserError(msg)
            return False
        url = base_url + '/api/zk/biometric/fingerprint/pull/status?jobId=%s' % job_id
        try:
            resp = requests.get(url, headers=controller._get_agent_headers(), timeout=20)
            text = resp.text or ''
            data = json.loads(text or '{}')
            state = data.get('state') or ('failed' if not data.get('success') else 'running')
            msg = data.get('message') or 'Fingerprint pull status: %s' % state
            job = self.env['entry.control.biometric.pull.job'].sudo().search([('job_id', '=', job_id)], limit=1)

            # Controller may return HTTP 200 with success=false when the job itself failed.
            # That is a valid job status, not a transport failure. Store the state/message
            # so the operator can see the exact failed step instead of only seeing a popup.
            if resp.status_code >= 200 and resp.status_code < 300 and data.get('jobId'):
                self._write_fingerprint_pull_result(state, msg, data, job_id=job_id)
                if job:
                    job._apply_progress_payload(data)
                return data

            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                msg = 'Fingerprint pull status failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_fingerprint_pull_result('failed', msg, data, job_id=job_id)
                if job:
                    job._apply_progress_payload(data)
                if raise_error:
                    raise UserError(msg)
                return False

            self._write_fingerprint_pull_result(state, msg, data, job_id=job_id)
            if job:
                job._apply_progress_payload(data)
            return data
        except Exception as ex:
            msg = 'Fingerprint pull status exception: %s' % str(ex)
            self._write_fingerprint_pull_result('failed', msg, job_id=job_id)
            if raise_error:
                raise UserError(msg)
            return False

    def _call_agent_fingerprint_pull_retry(self, job_id=None, raise_error=False):
        self.ensure_one()
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        job_id = job_id or self.last_fingerprint_pull_job_id
        if not base_url or not job_id:
            msg = 'Missing Controller Base URL or fingerprint pull Job ID.'
            if raise_error:
                raise UserError(msg)
            return False
        url = base_url + '/api/zk/biometric/fingerprint/pull/retry'
        try:
            resp = requests.post(url, headers=controller._get_agent_headers(), data=json.dumps({'jobId': job_id}), timeout=20)
            text = resp.text or ''
            data = json.loads(text or '{}')
            state = data.get('state') or 'queued'
            msg = data.get('message') or text
            self._write_fingerprint_pull_result(state, msg, data, job_id=job_id)
            job = self.env['entry.control.biometric.pull.job'].sudo().search([('job_id', '=', job_id)], limit=1)
            if job:
                job._apply_progress_payload(data)
            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                if raise_error:
                    raise UserError('Fingerprint pull retry failed. HTTP %s. Response: %s' % (resp.status_code, text))
                return False
            return data
        except Exception as ex:
            msg = 'Fingerprint pull retry exception: %s' % str(ex)
            self._write_fingerprint_pull_result('failed', msg, job_id=job_id)
            if raise_error:
                raise UserError(msg)
            return False

    def _call_agent_list_all_fingerprints(self, raise_error=False):
        self.ensure_one()

        if not self.enabled:
            msg = 'Device is disabled. Skip fingerprint list-all.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False

        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        url = base_url + '/api/zk/biometric/fingerprint/list-all'

        try:
            _logger.info(
                '[ENTRY CONTROL] List all fingerprints. Controller=%s, Device=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                url,
            )
            resp = requests.get(
                url,
                headers=controller._get_agent_headers(),
                timeout=60,
            )
            text = resp.text or ''
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Fingerprint list-all failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_biometric_result(msg)
                if raise_error:
                    raise UserError(msg)
                return False

            data = json.loads(text or '{}')
            if not data.get('success'):
                msg = 'Fingerprint list-all failed. Response: %s' % text
                self._write_biometric_result(msg)
                if raise_error:
                    raise UserError(msg)
                return False

            msg = 'Fingerprint list-all OK. Count=%s' % (data.get('count') or 0)
            self._write_biometric_result(msg)
            return data

        except Exception as ex:
            msg = 'Fingerprint list-all exception: %s' % str(ex)
            self._write_biometric_result(msg)
            _logger.exception('[ENTRY CONTROL] Fingerprint list-all exception.')
            if raise_error:
                raise UserError(msg)
            return False

    def _call_agent_download_fingerprint(self, user, finger_index=0, raise_error=False):
        """Download one fingerprint template by using the new list-all API first.
        The Agent lists templates exactly like the SDK demo, then Odoo filters by PIN/fingerIndex.
        """
        self.ensure_one()

        data = self._call_agent_list_all_fingerprints(raise_error=raise_error)
        if not data:
            return False

        requested_pin = str(user.pin or '').strip()
        requested_index = int(finger_index or 0)
        templates = data.get('templates') or []

        # First pass: exact PIN + exact finger index.
        for item in templates:
            pin = str(item.get('pin') or '').strip()
            idx = int(item.get('fingerIndex') or 0)
            if pin == requested_pin and idx == requested_index:
                if item.get('templateData'):
                    msg = 'Fingerprint template found by list-all. PIN=%s FingerIndex=%s Length=%s' % (
                        pin, idx, item.get('templateLength') or 0
                    )
                    self._write_biometric_result(msg)
                    return item

        # Second pass: numeric equivalent PIN, useful when device returns 0001 but Odoo stores 1.
        def _normalize_pin(value):
            value = str(value or '').strip()
            try:
                return str(int(value))
            except Exception:
                return value

        requested_pin_norm = _normalize_pin(requested_pin)
        for item in templates:
            pin = str(item.get('pin') or '').strip()
            idx = int(item.get('fingerIndex') or 0)
            if _normalize_pin(pin) == requested_pin_norm and idx == requested_index:
                if item.get('templateData'):
                    msg = 'Fingerprint template found by list-all using normalized PIN. DevicePIN=%s OdooPIN=%s FingerIndex=%s Length=%s' % (
                        pin, requested_pin, idx, item.get('templateLength') or 0
                    )
                    self._write_biometric_result(msg)
                    return item

        msg = 'Fingerprint template not found in list-all result. Requested PIN=%s FingerIndex=%s. Agent returned %s template(s).' % (
            requested_pin,
            requested_index,
            len(templates),
        )
        self._write_biometric_result(msg)
        if raise_error:
            raise UserError(msg)
        return False


    def _build_fingerprint_upload_payload(self, biometric):
        self.ensure_one()
        user = biometric.user_id
        timezone_id = int(getattr(user, 'access_timezone_id', 1) or 1)
        return {
            'pin': user.pin,
            'name': user._normalize_device_user_name(user.name or ''),
            'password': user.password or '',
            'cardNo': user.card_no or '',
            'privilege': int(user.privilege or '0'),
            'enabled': bool(user.enabled),
            'fingerIndex': int(biometric.finger_index or 0),
            'flag': int(biometric.flag or 1),
            'templateData': biometric.template_data or '',
            'templateLength': int(biometric.template_length or 0),
            'algorithm': biometric.algorithm or 'ZKFinger10',
            # Kept for API compatibility. The Controller intentionally keeps
            # fingerprint upload separate from access-rule/timezone writes.
            'applyAccessDefaults': True,
            'groupNo': int(getattr(user, 'access_group_no', 1) or 1),
            'authorizeTimezoneId': timezone_id,
            'authorizeDoorId': 1,
            'userTimezone': '1:1:1:1',
            'ensureFullDayTimezone': True,
        }

    def _start_fingerprint_push_job(self, biometrics, raise_error=False, connect_first=False):
        self.ensure_one()
        biometrics = biometrics or self.env['entry.control.biometric'].browse()
        total = len(biometrics)
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        odoo_base_url = self._get_odoo_public_base_url()

        if not self.enabled:
            msg = 'Device is disabled. Cannot start fingerprint push job.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        if controller.state != 'approved':
            msg = 'Controller is not approved. Cannot start fingerprint push job.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL before pushing fingerprints.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        if not odoo_base_url:
            msg = 'Odoo public base URL is missing. Set web.base.url before using Controller callback.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False

        if connect_first:
            # Kept for manual compatibility. The Controller job will also connect
            # the selected device from payload before running the SDK push.
            self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)

        job_uuid = uuid.uuid4().hex
        job_id = 'fppush-%s-%s' % (self.id, job_uuid[:16])
        payload = {
            'jobId': job_id,
            'controllerId': controller.controller_uid,
            'controllerToken': controller.api_token or '',
            'deviceId': self.id,
            'deviceCode': self.device_code or self.name or '',
            'deviceIp': self.device_ip or '',
            'devicePort': int(self.device_port or 4370),
            'machineNumber': int(self.machine_number or 1),
            'password': self.comm_key or '',
            'callbackProgressUrl': odoo_base_url + '/api/entry_control/biometric/fingerprint/push/progress',
            'odooDatabase': self.env.cr.dbname,
            'templates': [self._build_fingerprint_upload_payload(b) for b in biometrics],
        }

        job = self._apply_sync_job_payload(
            job_uid=job_id,
            job_type='fingerprint_push',
            data={
                'jobId': job_id,
                'jobType': 'fingerprint_push',
                'state': 'queued',
                'progressPercent': 0,
                'requestedCount': total,
                'totalCount': total,
                'processedCount': 0,
                'uploadedCount': 0,
                'failedCount': 0,
                'currentStep': 'Queued',
                'message': 'Waiting for Controller to start fingerprint push.',
            },
            name='Push All Fingerprints - %s' % self.display_name,
            payload=payload,
        )

        url = base_url + '/api/zk/biometric/fingerprint/push/start'
        try:
            _logger.info(
                '[ENTRY CONTROL] Start fingerprint push job. Controller=%s, Device=%s, Templates=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                total,
                url,
            )
            resp = requests.post(url, headers=controller._get_agent_headers(), data=json.dumps(payload), timeout=30)
            text = resp.text or ''

            # Old Controller compatibility: no async endpoint, caller can fall back to synchronous bulk.
            if resp.status_code == 404:
                _logger.warning('[ENTRY CONTROL] Controller does not support fingerprint push/start. Falling back to legacy bulk push. Url=%s', url)
                if job:
                    job.write({
                        'state': 'cancelled',
                        'message': 'Controller does not support async fingerprint push job. Falling back to legacy bulk push.',
                        'finished_at': fields.Datetime.now(),
                    })
                return False

            data = json.loads(text or '{}')
            if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                msg = 'Start fingerprint push job failed. HTTP %s. Response: %s' % (resp.status_code, text)
                if job:
                    job.write({'state': 'failed', 'last_error': msg, 'message': msg, 'finished_at': fields.Datetime.now()})
                    job._apply_controller_payload(data, job_type='fingerprint_push') if isinstance(data, dict) else None
                self._write_biometric_result(msg)
                if raise_error:
                    raise UserError(msg)
                return job

            if job:
                job._apply_controller_payload(data, job_type='fingerprint_push')
            self._write_biometric_result(data.get('message') or 'Fingerprint push job started. Job=%s' % job_id)
            return job
        except Exception as ex:
            msg = 'Start fingerprint push job exception: %s' % str(ex)
            if job:
                job.write({'state': 'failed', 'last_error': msg, 'message': msg, 'finished_at': fields.Datetime.now()})
            self._write_biometric_result(msg)
            _logger.exception('[ENTRY CONTROL] Start fingerprint push job exception.')
            if raise_error:
                raise UserError(msg)
            return job

    def _call_agent_fingerprint_push_status(self, job_id=None, raise_error=False):
        self.ensure_one()
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        job_id = job_id or ''
        if not job_id:
            job = self.env['entry.control.sync.job'].sudo().search([
                ('device_id', '=', self.id),
                ('job_type', '=', 'fingerprint_push'),
            ], order='create_date desc, id desc', limit=1)
            job_id = job.job_uid if job else ''
        if not base_url or not job_id:
            msg = 'Missing Controller Base URL or fingerprint push Job ID.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        url = base_url + '/api/zk/biometric/fingerprint/push/status?jobId=%s' % job_id
        try:
            resp = requests.get(url, headers=controller._get_agent_headers(), timeout=20)
            text = resp.text or ''
            data = json.loads(text or '{}')
            state = data.get('state') or ('failed' if not data.get('success') else 'running')
            msg = data.get('message') or 'Fingerprint push status: %s' % state
            job = self.env['entry.control.sync.job'].sudo().search([('job_uid', '=', job_id)], limit=1)

            if resp.status_code >= 200 and resp.status_code < 300 and data.get('jobId'):
                if job:
                    job._apply_controller_payload(data, job_type='fingerprint_push')
                self._apply_fingerprint_push_result_items(data)
                self._write_biometric_result(msg)
                return data

            msg = 'Fingerprint push status failed. HTTP %s. Response: %s' % (resp.status_code, text)
            if job:
                job._apply_controller_payload(data, job_type='fingerprint_push')
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False
        except Exception as ex:
            msg = 'Fingerprint push status exception: %s' % str(ex)
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return False

    def _apply_fingerprint_push_result_items(self, data):
        self.ensure_one()
        results = (data or {}).get('results') or []
        if not isinstance(results, list):
            return False
        User = self.env['entry.control.user'].sudo()
        Biometric = self.env['entry.control.biometric'].sudo()

        def _norm(value):
            value = str(value or '').strip()
            try:
                return str(int(value))
            except Exception:
                return value

        for item in results:
            if not isinstance(item, dict):
                continue
            pin = str(item.get('pin') or '').strip()
            if not pin:
                continue
            try:
                finger_index = int(item.get('fingerIndex') or 0)
            except Exception:
                finger_index = 0
            user = User.search([('controller_id', '=', self.controller_id.id), ('pin', '=', pin)], limit=1)
            if not user:
                # Fallback for devices that normalize numeric PINs by stripping leading zeroes.
                candidates = User.search([('controller_id', '=', self.controller_id.id)])
                user = candidates.filtered(lambda u: _norm(u.pin) == _norm(pin))[:1]
            if not user:
                continue
            biometric = Biometric.search([
                ('user_id', '=', user.id),
                ('biometric_type', '=', 'fingerprint'),
                ('finger_index', '=', finger_index),
            ], limit=1)
            if not biometric:
                continue
            msg = item.get('message') or (data.get('message') or '')
            if item.get('success'):
                biometric._write_result('synced', msg or 'Fingerprint push OK.', self)
            else:
                biometric._write_result('failed', msg or 'Fingerprint push failed.', self)
        return True

    def _call_agent_upload_fingerprints_bulk(self, biometrics, raise_error=False, connect_first=False):
        """Use Controller bulk API to push many fingerprint templates in one SDK session.

        Returns a result dict like _push_fingerprints_for_users, or None when
        the Controller does not support /api/zk/biometric/fingerprint/push-all
        so the caller can fall back to the old per-template upload API.
        """
        self.ensure_one()
        biometrics = biometrics or self.env['entry.control.biometric'].browse()
        total = len(biometrics)

        if not total:
            return {'total': 0, 'ok': 0, 'errors': [], 'message': 'No fingerprint template to push.'}

        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL before pushing fingerprints.'
            self._write_biometric_result(msg)
            if raise_error:
                raise UserError(msg)
            return {'total': total, 'ok': 0, 'errors': [msg], 'message': msg}

        if connect_first:
            connect_ok = self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)
            if not connect_ok:
                msg = 'Fingerprint bulk push aborted: device connect failed.'
                return {'total': total, 'ok': 0, 'errors': [msg], 'message': msg}

        payload = {
            'deviceId': self.id,
            'deviceCode': self.device_code or self.name or '',
            'templates': [self._build_fingerprint_upload_payload(b) for b in biometrics],
        }
        url = base_url + '/api/zk/biometric/fingerprint/push-all'
        timeout = max(60, min(1800, 20 + total * 5))

        try:
            _logger.info(
                '[ENTRY CONTROL] Push all fingerprints bulk. Controller=%s, Device=%s, Templates=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                total,
                url,
            )
            resp = requests.post(
                url,
                headers=controller._get_agent_headers(),
                data=json.dumps(payload),
                timeout=timeout,
            )
            text = resp.text or ''

            if resp.status_code == 404:
                _logger.warning('[ENTRY CONTROL] Controller does not support fingerprint push-all. Falling back to per-template upload. Url=%s', url)
                return None

            data = json.loads(text or '{}')
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Fingerprint bulk push failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_biometric_result(msg)
                if raise_error:
                    raise UserError(msg)
                return {'total': total, 'ok': 0, 'errors': [msg], 'message': msg}

            results = data.get('results') or []
            ok_count = int(data.get('uploadedCount') or 0)
            errors = data.get('errors') or []
            if isinstance(errors, str):
                errors = [errors]

            def _norm_pin(value):
                value = str(value or '').strip()
                try:
                    return str(int(value))
                except Exception:
                    return value

            result_by_exact = {}
            result_by_norm = {}
            for item in results:
                if not isinstance(item, dict):
                    continue
                pin = str(item.get('pin') or '').strip()
                try:
                    idx = int(item.get('fingerIndex') or 0)
                except Exception:
                    idx = 0
                result_by_exact[(pin, idx)] = item
                result_by_norm[(_norm_pin(pin), idx)] = item

            for biometric in biometrics:
                pin = str(biometric.user_id.pin or '').strip()
                idx = int(biometric.finger_index or 0)
                item = result_by_exact.get((pin, idx)) or result_by_norm.get((_norm_pin(pin), idx))
                if item:
                    item_msg = item.get('message') or data.get('message') or ''
                    if item.get('success'):
                        biometric._write_result('synced', item_msg or 'Fingerprint bulk push OK.', self)
                    else:
                        biometric._write_result('failed', item_msg or 'Fingerprint bulk push failed.', self)
                elif data.get('success') and ok_count == total:
                    biometric._write_result('synced', data.get('message') or 'Fingerprint bulk push OK.', self)

            message = data.get('message') or 'Fingerprint bulk push completed. Pushed %s/%s.' % (ok_count, total)
            if not data.get('success') and not errors:
                errors = [message]
            if not results and not data.get('success'):
                for biometric in biometrics:
                    biometric._write_result('failed', message, self)
            self._write_biometric_result(message)
            return {'total': total, 'ok': ok_count, 'errors': errors, 'message': message}

        except UserError:
            raise
        except Exception as ex:
            msg = 'Fingerprint bulk push exception: %s' % str(ex)
            self._write_biometric_result(msg)
            _logger.exception('[ENTRY CONTROL] Fingerprint bulk push exception.')
            if raise_error:
                raise UserError(msg)
            return {'total': total, 'ok': 0, 'errors': [msg], 'message': msg}

    def _call_agent_upload_fingerprint(self, biometric, raise_error=False, connect_first=False):
        self.ensure_one()

        if not self.enabled:
            msg = 'Device is disabled. Skip fingerprint upload.'
            self._write_biometric_result(msg)
            biometric._write_result('failed', msg, self)
            if raise_error:
                raise UserError(msg)
            return False

        if not self.sync_users:
            msg = 'User sync is disabled for this device. Skip fingerprint upload.'
            self._write_biometric_result(msg)
            biometric._write_result('failed', msg, self)
            if raise_error:
                raise UserError(msg)
            return False

        if not biometric.template_data:
            msg = 'Template Data is empty. Pull template from a device first.'
            self._write_biometric_result(msg)
            biometric._write_result('failed', msg, self)
            if raise_error:
                raise UserError(msg)
            return False

        if connect_first:
            connect_ok = self._call_agent_connect_device(raise_error=raise_error, force_reconnect=True)
            if not connect_ok:
                return False

        user = biometric.user_id
        controller = self.controller_id
        base_url = controller.get_agent_base_url()
        url = base_url + '/api/zk/biometric/fingerprint/upload'

        payload = self._build_fingerprint_upload_payload(biometric)

        try:
            _logger.info(
                '[ENTRY CONTROL] Upload fingerprint. Controller=%s, Device=%s, User=%s, FingerIndex=%s, Url=%s',
                controller.controller_uid,
                self.device_code or self.name,
                user.pin,
                biometric.finger_index,
                url,
            )
            resp = requests.post(
                url,
                headers=controller._get_agent_headers(),
                data=json.dumps(payload),
                timeout=20,
            )
            text = resp.text or ''
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Fingerprint upload failed. HTTP %s. Response: %s' % (resp.status_code, text)
                self._write_biometric_result(msg)
                biometric._write_result('failed', msg, self)
                if raise_error:
                    raise UserError(msg)
                return False

            msg = 'Fingerprint upload OK. Response: %s' % text
            self._write_biometric_result(msg)
            biometric._write_result('synced', msg, self)
            return True

        except Exception as ex:
            msg = 'Fingerprint upload exception: %s' % str(ex)
            self._write_biometric_result(msg)
            biometric._write_result('failed', msg, self)
            _logger.exception('[ENTRY CONTROL] Fingerprint upload exception.')
            if raise_error:
                raise UserError(msg)
            return False

    def _write_biometric_result(self, message):
        self.write({
            'last_biometric_at': fields.Datetime.now(),
            'last_biometric_message': message,
        })
