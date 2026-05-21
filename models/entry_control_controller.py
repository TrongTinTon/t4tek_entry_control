from odoo import models, fields, api
from odoo.exceptions import UserError
import uuid
import json
import logging
import requests

_logger = logging.getLogger(__name__)


class EntryControlController(models.Model):
    _name = 'entry.control.controller'
    _description = 'Entry Control Controller Registry'
    _order = 'last_seen_at desc, id desc'

    name = fields.Char(string='Controller Name', required=True, default='New Controller')
    controller_uid = fields.Char(string='Controller ID', required=True, index=True, copy=False)

    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('suspicious', 'Suspicious'),
        ('blocked', 'Blocked'),
    ], string='State', required=True, default='pending', index=True)

    active_controller = fields.Boolean(string='Allowed to Push Attendance', default=False)
    api_token = fields.Char(string='Controller API Token', default=lambda self: uuid.uuid4().hex, copy=False, readonly=True)

    # API key used by Odoo when calling back to the Controller local/public API.
    agent_api_key = fields.Char(string='Controller API Key', default='dev-secret-key')
    controller_base_url = fields.Char(
        string='Controller Base URL',
        help='Public Controller URL used by Odoo to call Controller APIs, for example https://tinton.tail52e8f6.ts.net. Do not include a trailing slash.',
    )

    # Legacy discovery diagnostics kept for backward compatibility only.
    service_name = fields.Char(string='Zeroconf Service Name')
    service_type = fields.Char(string='Zeroconf Service Type', default='_entry-controller._tcp.local.')
    advertised_ip = fields.Char(string='Advertised Controller IP')
    api_port = fields.Integer(string='Controller API Port')
    api_version = fields.Char(string='API Version')

    # Legacy approved endpoint fields kept for backward compatibility only.
    # Attendance validation now uses approved state + controller token, not source IP/port.
    allowed_ip = fields.Char(string='Legacy Approved Source IP')
    allowed_api_port = fields.Integer(string='Legacy Approved API Port')

    last_seen_ip = fields.Char(string='Last Seen Source IP')
    last_seen_at = fields.Datetime(string='Last Seen At')
    first_seen_at = fields.Datetime(string='First Seen At', default=fields.Datetime.now, readonly=True)
    last_payload = fields.Text(string='Last Controller Payload')
    note = fields.Text(string='Note')

    last_heartbeat_at = fields.Datetime(string='Last Heartbeat At', readonly=True)
    heartbeat_state = fields.Selection([
        ('online', 'Online'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('offline', 'Offline'),
    ], string='Heartbeat Reported State', default='offline', readonly=True,
        help='Internal raw state reported by the Controller heartbeat. Use Runtime State in UI.')
    heartbeat_effective_state = fields.Selection([
        ('online', 'Online'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('offline', 'Offline'),
    ], string='Runtime State', compute='_compute_heartbeat_runtime')
    heartbeat_is_online = fields.Boolean(string='Online', compute='_compute_heartbeat_runtime')
    heartbeat_age_seconds = fields.Integer(string='Heartbeat Age Seconds', compute='_compute_heartbeat_runtime')
    heartbeat_message = fields.Char(string='Heartbeat Message', readonly=True)
    heartbeat_device_connected = fields.Boolean(string='Device Last Reported Connected', readonly=True,
        help='Last device connection flag reported while the Controller was online. If the Controller is offline, this is only a last-known value.')
    heartbeat_push_worker_running = fields.Boolean(string='PushWorker Running', readonly=True)
    heartbeat_worker_running = fields.Boolean(string='Heartbeat Worker Running', readonly=True)
    heartbeat_local_db_ok = fields.Boolean(string='Local DB OK', readonly=True)
    heartbeat_pending_outbox_count = fields.Integer(string='Pending Events', readonly=True)
    heartbeat_failed_outbox_count = fields.Integer(string='Failed/Retry Events', readonly=True)
    heartbeat_last_event_at = fields.Datetime(string='Last Event At', readonly=True)
    heartbeat_last_push_at = fields.Datetime(string='Last Push At', readonly=True)
    heartbeat_app_version = fields.Char(string='App Version', readonly=True)

    # Auto Connect Devices has been removed. Devices are connected manually
    # from the Device form, or by the Windows Agent/operator before syncing.

    device_ids = fields.One2many(
        'entry.control.device',
        'controller_id',
        string='Managed Devices'
    )
    primary_device_id = fields.Many2one(
        'entry.control.device',
        string='Primary Device',
        domain="[('controller_id', '=', id), ('enabled', '=', True)]",
    )

    user_ids = fields.One2many(
        'entry.control.user',
        'controller_id',
        string='Legacy Managed Users'
    )

    attendance_log_ids = fields.One2many(
        'entry.control.log',
        'controller_ref_id',
        string='Attendance Logs'
    )
    security_event_ids = fields.One2many(
        'entry.control.security.event',
        'controller_id',
        string='Security Events'
    )

    _sql_constraints = [
        ('controller_uid_unique', 'unique(controller_uid)', 'Controller ID must be unique.'),
    ]

    @api.depends('last_heartbeat_at', 'heartbeat_state')
    def _compute_heartbeat_runtime(self):
        now = fields.Datetime.now()
        threshold_seconds = 180
        for record in self:
            if record.last_heartbeat_at:
                age = int((now - fields.Datetime.to_datetime(record.last_heartbeat_at)).total_seconds())
                if age < 0:
                    age = 0
            else:
                age = 0

            record.heartbeat_age_seconds = age
            if not record.last_heartbeat_at or age > threshold_seconds:
                record.heartbeat_effective_state = 'offline'
                record.heartbeat_is_online = False
            else:
                record.heartbeat_effective_state = record.heartbeat_state or 'online'
                record.heartbeat_is_online = record.heartbeat_effective_state in ('online', 'warning')

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

    def action_approve(self):
        count = 0
        for record in self:
            record.write({
                'state': 'approved',
                'active_controller': True,
            })
            count += 1
        return self._notification_action('Approve Controller', 'Approved %s controller(s).' % count)

    def action_approve_current_endpoint(self):
        count = 0
        for record in self:
            record.write({
                'state': 'approved',
                'active_controller': True,
            })
            count += 1
        return self._notification_action('Approve Controller', 'Approved %s controller(s).' % count)

    def action_block(self):
        count = 0
        for record in self:
            record.write({
                'state': 'blocked',
                'active_controller': False,
            })
            count += 1
        return self._notification_action('Block Controller', 'Blocked %s controller(s).' % count, notification_type='warning')

    def action_set_pending(self):
        count = 0
        for record in self:
            record.write({
                'state': 'pending',
                'active_controller': False,
            })
            count += 1
        return self._notification_action('Set Pending', 'Set %s controller(s) to pending.' % count, notification_type='warning')

    def action_regenerate_token(self):
        count = 0
        for record in self:
            record.write({'api_token': uuid.uuid4().hex})
            count += 1
        return self._notification_action(
            'Regenerate Token',
            'Generated new API token for %s controller(s). Existing Agent registration must be updated with the new token.' % count,
            notification_type='warning',
            sticky=True,
        )

    def action_copy_last_seen_to_allowed(self):
        count = 0
        for record in self:
            record.write({
                'allowed_ip': record.last_seen_ip or record.advertised_ip,
                'allowed_api_port': record.api_port or record.allowed_api_port,
            })
            count += 1
        return self._notification_action('Copy Endpoint', 'Copied last seen endpoint to legacy allowed endpoint for %s controller(s).' % count)

    def action_sync_all_enabled_users(self):
        """Strict full sync all enabled Device Users and then push stored fingerprints.

        Odoo is the source of truth for users. Fingerprint templates stored in
        Biometric Templates are pushed only after the user full-sync job has
        completed, because a device cannot accept a fingerprint template for a
        PIN that has not been created yet.
        """
        for record in self:
            users = self.env['entry.control.user'].sudo().search([
                ('enabled', '=', True),
                ('sync_enabled', '=', True),
                ('pin', '!=', False),
            ], order='pin, name')
            devices = record.device_ids.filtered(lambda d: d.enabled and d.sync_users)
            # Allow an empty Device User list.
            # This is a valid strict-sync use case: Odoo is the source of truth,
            # so an empty list means all users that currently exist on the
            # physical device should be deleted by the Controller Agent.
            if not devices:
                raise UserError('No enabled devices found for this controller.')

            fingerprint_templates = users.mapped('biometric_ids').filtered(
                lambda b: b.biometric_type == 'fingerprint' and bool(b.template_data)
            )
            sync_fingerprints = bool(fingerprint_templates)

            ok_count = 0
            errors = []
            fingerprint_messages = []
            for device in devices:
                try:
                    ok = device._call_agent_sync_users_full(
                        users,
                        delete_missing=True,
                        preserve_pins=[],
                        raise_error=False,
                        connect_first=True,
                        # Start async so Odoo can show progress on the Device form.
                        # Use Check Full Sync Job to poll progress; fingerprints are pushed
                        # automatically by that check after the user job succeeds.
                        wait=False,
                        sync_fingerprints=sync_fingerprints,
                    )
                    if ok:
                        ok_count += 1
                        if sync_fingerprints and device.last_biometric_message:
                            fingerprint_messages.append('%s: %s' % (device.display_name, device.last_biometric_message))
                    else:
                        errors.append('%s: %s' % (device.display_name, device.last_user_sync_message or 'Full sync failed'))
                except Exception as ex:
                    errors.append('%s: %s' % (device.display_name, str(ex)))

            if errors:
                raise UserError('Strict full sync finished on %s/%s device(s). User count: %s. Fingerprint templates: %s. Errors: %s' % (
                    ok_count, len(devices), len(users), len(fingerprint_templates), '; '.join(errors[:10])
                ))

            if users:
                if sync_fingerprints:
                    message = (
                        'Strict full sync job started on %s device(s). User count: %s. Fingerprint templates pending after user sync succeeds: %s. Open Devices and click Check Full Sync Job to refresh the progress bar.'
                        % (ok_count, len(users), len(fingerprint_templates))
                    )
                else:
                    message = (
                        'Strict full sync job started on %s device(s). User count: %s. Missing users on device will be deleted if deleteMissing=true. Open Devices and click Check Full Sync Job to refresh the progress bar.'
                        % (ok_count, len(users))
                    )
            else:
                message = (
                    'Started strict full sync on %s device(s). User count: 0. Empty list was confirmed with allowEmptyFullSync=true and will clear users on the device.'
                    % ok_count
                )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync All Users started',
                    'message': message,
                    'type': 'success' if users else 'warning',
                    'sticky': True,
                }
            }

    def action_push_all_fingerprints(self):
        """Push all stored fingerprint templates to all enabled devices of this Controller."""
        users = self.env['entry.control.user'].sudo().search([
            ('enabled', '=', True),
            ('sync_enabled', '=', True),
            ('pin', '!=', False),
        ], order='pin, name')

        messages = []
        notification_type = 'success'
        for record in self:
            devices = record.device_ids.filtered(lambda d: d.enabled and d.sync_users)
            if not devices:
                notification_type = 'warning'
                messages.append('%s: no enabled/sync-enabled device found.' % record.display_name)
                continue

            for device in devices:
                result = device._push_fingerprints_for_users(users, raise_error=False, connect_first=True)
                total = result.get('total') or 0
                ok = result.get('ok') or 0
                errors = result.get('errors') or []
                if errors:
                    notification_type = 'warning'
                messages.append('%s: pushed %s/%s%s' % (
                    device.display_name,
                    ok,
                    total,
                    ('. Errors: %s' % '; '.join(errors[:3])) if errors else '',
                ))

        return self._notification_action(
            'Push All Fingerprints',
            '; '.join(messages[:10]),
            notification_type=notification_type,
            sticky=(notification_type != 'success'),
        )

    def action_refresh_sync_progress(self):
        messages = []
        notification_type = 'success'
        for record in self:
            devices = record.device_ids.filtered(lambda d: d.enabled and d.last_user_sync_job_id)
            if not devices:
                messages.append('%s: no active full sync job found.' % record.display_name)
                notification_type = 'warning'
                continue
            for device in devices:
                data = device._call_agent_full_sync_status(raise_error=False)
                state = data.get('state') if isinstance(data, dict) else device.last_user_sync_state
                if state == 'success':
                    users = self.env['entry.control.user'].sudo().search([
                        ('enabled', '=', True),
                        ('sync_enabled', '=', True),
                        ('pin', '!=', False),
                    ], order='pin, name')
                    device._push_fingerprints_for_users(users, raise_error=False, connect_first=False)
                if state not in ('success', 'queued', 'running'):
                    notification_type = 'warning'
                messages.append(
                    '%s: state=%s, progress=%s%%, processed=%s/%s' % (
                        device.display_name,
                        state or device.last_user_sync_state or 'unknown',
                        device.last_user_sync_progress_percent or 0,
                        device.last_user_sync_processed_count or 0,
                        device.last_user_sync_total_count or device.last_user_sync_requested_count or 0,
                    )
                )
        return self._notification_action('Sync Progress', '; '.join(messages[:10]), notification_type=notification_type, sticky=(notification_type != 'success'))

    def action_refresh_runtime_health(self):
        messages = []
        notification_type = 'success'
        for record in self:
            state = record.heartbeat_effective_state or 'offline'
            if state in ('offline', 'error'):
                notification_type = 'danger'
            elif state == 'warning' and notification_type != 'danger':
                notification_type = 'warning'
            messages.append('%s: %s, last=%s, pending=%s, failed=%s, device=%s, push=%s, db=%s' % (
                record.display_name,
                state,
                record.last_heartbeat_at or 'never',
                record.heartbeat_pending_outbox_count or 0,
                record.heartbeat_failed_outbox_count or 0,
                'connected' if record.heartbeat_device_connected else 'disconnected',
                'running' if record.heartbeat_push_worker_running else 'stopped',
                'ok' if record.heartbeat_local_db_ok else 'error',
            ))
        return self._notification_action('Runtime Health', '; '.join(messages[:10]), notification_type=notification_type, sticky=(notification_type != 'success'))

    def action_disconnect_agent(self):
        total_devices = 0
        for record in self:
            record._call_agent_disconnect(raise_error=True)

            # Controller-level disconnect is a global Agent disconnect command.
            # The Agent API does not return a specific device id, so the server
            # must also update the connection state of managed devices locally.
            # Keep disabled devices as disabled; mark all other managed devices
            # as disconnected so the Odoo UI reflects the actual Agent state.
            devices = record.device_ids.filtered(lambda d: d.connection_state != 'disabled')
            total_devices += len(devices)
            for device in devices:
                device._write_connect_result(
                    'disconnected',
                    'Disconnect command sent from Controller. Server marked this device as disconnected.'
                )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Disconnect Controller',
                'message': 'Disconnect command sent. Updated %s managed device(s) on server.' % total_devices,
                'type': 'success',
                'sticky': False,
            }
        }


    def action_generate_devices_from_agent(self):
        """Create/update Devices from the approved Controller Agent inventory."""
        total_created = 0
        total_updated = 0
        total_skipped = 0
        messages = []

        for record in self:
            if record.state != 'approved':
                raise UserError('Only approved controllers can generate Devices from Agent inventory.')

            data = record._call_agent_get_all_devices(raise_error=True)
            result = record._upsert_devices_from_agent_inventory(data)
            total_created += result.get('created', 0)
            total_updated += result.get('updated', 0)
            total_skipped += result.get('skipped', 0)
            if result.get('message'):
                messages.append('%s: %s' % (record.display_name, result.get('message')))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Generate Devices',
                'message': 'Created: %s. Updated: %s. Skipped: %s.%s' % (
                    total_created,
                    total_updated,
                    total_skipped,
                    (' ' + '; '.join(messages[:5])) if messages else '',
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    def _call_agent_get_all_devices(self, raise_error=False):
        self.ensure_one()
        base_url = self.get_agent_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            if raise_error:
                raise UserError(msg)
            return {}

        headers = self._get_agent_headers()
        urls = [
            base_url + '/api/get_all_device',
            base_url + '/api/zk/device/diagnostic',
        ]
        last_error = ''

        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                text = resp.text or ''
                if resp.status_code == 404:
                    last_error = 'Agent endpoint not found. HTTP 404. Url=%s. Response=%s' % (url, text)
                    continue

                data = json.loads(text or '{}')
                if resp.status_code < 200 or resp.status_code >= 300 or not data.get('success'):
                    msg = 'Get Agent devices failed. HTTP %s. Url=%s. Response: %s' % (resp.status_code, url, text)
                    if raise_error:
                        raise UserError(msg)
                    return {}

                return data
            except Exception as ex:
                last_error = 'Get Agent devices exception. Url=%s. Error=%s' % (url, str(ex))
                _logger.exception('[ENTRY CONTROL] Get Agent devices exception.')
                continue

        if raise_error:
            raise UserError(last_error or 'Agent does not expose device inventory API.')
        return {}

    def _upsert_devices_from_agent_inventory(self, data):
        self.ensure_one()
        Device = self.env['entry.control.device'].sudo()
        data = data or {}
        devices = data.get('devices') or []

        # Backward compatible fallback: if Agent returns only status fields, convert it to one device item.
        if not devices and (data.get('deviceEndpoint') or data.get('deviceIp')):
            devices = [data]

        created = 0
        updated = 0
        skipped = 0
        first_device = False

        for item in devices:
            if not isinstance(item, dict):
                skipped += 1
                continue

            # Generate must trust only inventory items sourced from controller-local-settings.json.
            # This prevents stale device generation from Agent runtime state, UI textboxes,
            # _currentDeviceEndpoint, or legacy /status-style responses.
            source = self._first_agent_value(item, 'source')
            settings_source = self._first_agent_value(item, 'settingsSource')
            device_settings_saved = self._to_bool(
                item.get('deviceSettingsSaved')
            )
            if source != 'controller-local-settings' or settings_source != 'controller-local-settings.json' or not device_settings_saved:
                skipped += 1
                continue

            vals = self._build_device_vals_from_agent_item(item)
            if not vals.get('device_ip'):
                skipped += 1
                continue

            device = Device.browse()
            device_code = vals.get('device_code')
            if device_code:
                device = Device.search([
                    ('controller_id', '=', self.id),
                    ('device_code', '=', device_code),
                ], limit=1)

            if not device:
                device = Device.search([
                    ('controller_id', '=', self.id),
                    ('device_ip', '=', vals.get('device_ip')),
                    ('device_port', '=', vals.get('device_port') or 4370),
                    ('machine_number', '=', vals.get('machine_number') or 1),
                ], limit=1)

            vals['controller_id'] = self.id
            if device:
                # Do not overwrite manually entered comm_key if Agent does not return one.
                if not vals.get('comm_key'):
                    vals.pop('comm_key', None)
                device.write(vals)
                updated += 1
            else:
                vals.setdefault('enabled', True)
                vals.setdefault('sync_users', True)
                device = Device.create(vals)
                created += 1

            if not first_device:
                first_device = device

        if first_device and not self.primary_device_id:
            self.write({'primary_device_id': first_device.id})
            if not first_device.is_primary:
                first_device.write({'is_primary': True})

        return {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'message': 'Agent returned %s device item(s).' % len(devices),
        }

    def _build_device_vals_from_agent_item(self, item):
        self.ensure_one()
        endpoint = self._first_agent_value(item, 'deviceEndpoint')
        ip = self._first_agent_value(item, 'deviceIp')
        port = self._to_int(self._first_agent_value(item, 'devicePort'), 4370)

        if not ip and endpoint:
            ip, parsed_port = self._split_endpoint(endpoint)
            if parsed_port:
                port = parsed_port

        machine_number = self._to_int(self._first_agent_value(item, 'machineNumber'), 1)
        device_code = self._first_agent_value(item, 'deviceCode')
        if not device_code:
            device_code = self._build_agent_device_code(ip, port, machine_number)

        connected = bool(item.get('connected'))
        connection_state = self._first_agent_value(item, 'connectionState') or ('connected' if connected else 'disconnected')
        if connection_state not in ('unknown', 'connected', 'disconnected', 'failed', 'disabled'):
            connection_state = 'unknown'

        name = self._first_agent_value(item, 'name') or 'Device %s:%s' % (ip or 'unknown', port or 4370)

        return {
            'name': name,
            'device_code': device_code,
            'device_ip': ip or '',
            'device_port': port or 4370,
            'machine_number': machine_number or 1,
            'comm_key': self._first_agent_value(item, 'commKey'),
            'is_primary': bool(item.get('isPrimary') or item.get('is_primary')),
            'connection_state': connection_state,
            'last_status_at': fields.Datetime.now(),
            'last_status_message': self._build_device_inventory_message(item, ip, port, machine_number, connection_state),
            'serial_number': self._first_agent_value(item, 'serialNumber'),
            'platform': self._first_agent_value(item, 'platform'),
            'firmware_version': self._first_agent_value(item, 'firmwareVersion'),
            'mac_address': self._first_agent_value(item, 'macAddress'),
            'agent_device_endpoint': endpoint or ('%s:%s' % (ip, port) if ip else ''),
            'last_diagnostic_at': fields.Datetime.now(),
            'last_diagnostic_message': self._first_agent_value(item, 'lastDiagnosticMessage') or (item.get('message') or ''),
        }

    def _build_device_inventory_message(self, item, ip, port, machine_number, connection_state):
        source = self._first_agent_value(item, 'source') or 'unknown'
        settings_source = self._first_agent_value(item, 'settingsSource') or ''
        endpoint = self._first_agent_value(item, 'deviceEndpoint') or (('%s:%s' % (ip, port)) if ip else '')
        parts = [
            'Imported from Agent inventory',
            'Endpoint=%s' % endpoint if endpoint else '',
            'MachineNo=%s' % int(machine_number or 1),
            'State=%s' % (connection_state or 'unknown'),
            'Source=%s' % source,
            'Settings=%s' % settings_source if settings_source else '',
        ]
        return '; '.join([p for p in parts if p])

    def _first_agent_value(self, data, *keys):
        data = data or {}
        for key in keys:
            if key in data and data.get(key) not in (None, False):
                value = data.get(key)
                return value.strip() if isinstance(value, str) else value
        return ''

    def _to_int(self, value, default=0):
        try:
            if value in (None, ''):
                return default
            return int(value)
        except Exception:
            return default

    def _to_bool(self, value):
        if isinstance(value, bool):
            return value
        if value in (None, ''):
            return False
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1', 'yes', 'y')
        return bool(value)

    def _split_endpoint(self, endpoint):
        endpoint = str(endpoint or '').strip()
        if not endpoint:
            return '', 0
        if ':' not in endpoint:
            return endpoint, 0
        ip, port_text = endpoint.rsplit(':', 1)
        return ip.strip(), self._to_int(port_text, 0)

    def _build_agent_device_code(self, ip, port, machine_number):
        ip = str(ip or 'unknown').strip().replace('.', '-').replace(':', '-')
        return 'ZK-%s-%s-M%s' % (ip, int(port or 4370), int(machine_number or 1))

    @api.onchange('controller_base_url')
    def _onchange_controller_base_url(self):
        for record in self:
            normalized = record._normalize_controller_base_url(record.controller_base_url)
            if normalized and normalized != record.controller_base_url:
                record.controller_base_url = normalized

    def _normalize_controller_base_url(self, value):
        value = (value or '').strip()
        if not value:
            return ''
        if '://' not in value:
            value = 'https://' + value
        return value.rstrip('/')

    def get_agent_base_url(self):
        self.ensure_one()
        return self._normalize_controller_base_url(self.controller_base_url)

    def _get_agent_headers(self):
        self.ensure_one()
        return {
            'Content-Type': 'application/json',
            'X-API-Key': self.agent_api_key or 'dev-secret-key',
        }

    def _call_agent_disconnect(self, raise_error=False):
        self.ensure_one()
        base_url = self.get_agent_base_url()
        if not base_url:
            msg = 'Controller Base URL is missing. Please set Controller Base URL, for example https://tinton.tail52e8f6.ts.net.'
            if raise_error:
                raise UserError(msg)
            return False

        url = base_url + '/api/zk/device/disconnect'
        try:
            resp = requests.post(url, headers=self._get_agent_headers(), timeout=10)
            if resp.status_code < 200 or resp.status_code >= 300:
                msg = 'Agent disconnect failed. HTTP %s. Response: %s' % (resp.status_code, resp.text or '')
                if raise_error:
                    raise UserError(msg)
                return False
            return True
        except Exception as ex:
            _logger.exception('[ENTRY CONTROL] Agent disconnect exception.')
            if raise_error:
                raise UserError(str(ex))
            return False

class EntryControlSecurityEvent(models.Model):
    _name = 'entry.control.security.event'
    _description = 'Entry Control Security Event'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Event', required=True)
    controller_id = fields.Many2one('entry.control.controller', string='Controller', ondelete='set null')
    payload_controller_id = fields.Char(string='Payload Controller ID')
    source_ip = fields.Char(string='Source IP')
    event_type = fields.Selection([
        ('invalid_registration_secret', 'Invalid Registration Secret'),
        ('invalid_discovery_secret', 'Invalid Discovery Secret'),
        ('blocked_controller_hello', 'Blocked Controller Hello'),
        ('unknown_controller_attendance', 'Unknown Controller Attendance'),
        ('blocked_controller_attendance', 'Blocked Controller Attendance'),
        ('unapproved_controller_attendance', 'Unapproved Controller Attendance'),
        ('invalid_controller_token', 'Invalid Controller Token'),
        ('unexpected_controller_ip', 'Unexpected Controller IP'),
        ('unexpected_controller_port', 'Unexpected Controller Port'),
        ('agent_connect_failed', 'Agent Connect Failed'),
        ('user_sync_failed', 'User Sync Failed'),
    ], string='Event Type', required=True)
    message = fields.Text(string='Message')
    raw_payload = fields.Text(string='Raw Payload')
