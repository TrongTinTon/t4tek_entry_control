import json
import logging
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EntryControlBiometric(models.Model):
    _name = 'entry.control.biometric'
    _description = 'Entry Control Biometric Template'
    _order = 'user_id, biometric_type, finger_index, id'

    name = fields.Char(string='Name', compute='_compute_name', store=True)

    user_id = fields.Many2one(
        'entry.control.user',
        string='Device User',
        required=True,
        ondelete='cascade',
    )

    controller_id = fields.Many2one(
        'entry.control.controller',
        string='Controller',
        related='user_id.controller_id',
        store=True,
        readonly=True,
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='user_id.employee_id',
        store=True,
        readonly=True,
    )

    biometric_type = fields.Selection([
        ('fingerprint', 'Fingerprint'),
    ], string='Type', required=True, default='fingerprint')

    finger_index = fields.Integer(string='Finger Index', default=0)
    flag = fields.Integer(string='Flag', default=1)
    algorithm = fields.Selection([
        ('ZKFinger10', 'ZKFinger 10.0 / Ex'),
        ('ZKFinger13', 'ZKFinger VX13.0'),
        ('SSR', 'SSR Legacy'),
    ], string='Algorithm', default='ZKFinger10')

    template_data = fields.Text(
        string='Template Data',
        readonly=True,
        help='Fingerprint template payload is managed by the Agent pull/upload workflow. Manual editing is disabled to avoid corrupting biometric data.',
    )
    template_length = fields.Integer(string='Template Length')
    template_hash = fields.Char(string='Template Hash', readonly=True, copy=False, index=True)

    source_device_id = fields.Many2one(
        'entry.control.device',
        string='Source Device',
        domain="[('enabled', '=', True)]",
        help='Thiết bị nguồn để kết nối và pull template vân tay về Odoo. Bắt buộc chọn trước khi pull.'
    )


    sync_state = fields.Selection([
        ('none', 'Not Pulled'),
        ('pulled', 'Pulled'),
        ('synced', 'Synced to Device'),
        ('failed', 'Failed'),
    ], default='none', string='Template State')

    last_sync_at = fields.Datetime(string='Last Sync At')
    last_sync_message = fields.Text(string='Last Sync Message')
    last_sync_device_id = fields.Many2one('entry.control.device', string='Last Sync Device')

    _sql_constraints = [
        (
            'finger_unique_per_user',
            'unique(user_id, biometric_type, finger_index)',
            'Each user can only have one biometric template per type and finger index.'
        ),
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

    @api.depends('user_id', 'biometric_type', 'finger_index')
    def _compute_name(self):
        for rec in self:
            pin = rec.user_id.pin if rec.user_id else ''
            rec.name = '%s - %s #%s' % (pin, rec.biometric_type or 'biometric', rec.finger_index)

    @api.constrains('finger_index')
    def _check_finger_index(self):
        for rec in self:
            if rec.biometric_type == 'fingerprint' and (rec.finger_index < 0 or rec.finger_index > 9):
                raise UserError('Finger Index must be from 0 to 9.')

    def action_connect_source_device(self):
        messages = []
        for rec in self:
            device = rec._get_source_device(raise_error=True)
            device._call_agent_connect_device(raise_error=True, force_reconnect=True)
            msg = 'Selected source device connected: %s' % device.display_name
            rec._write_result('none', msg, device)
            messages.append('%s: %s' % (rec.display_name, msg))
        return self._notification_action('Connect Selected Device', '; '.join(messages[:5]), notification_type='success')

    def action_pull_from_device(self):
        messages = []
        for rec in self:
            rec._pull_from_device(raise_error=True)
            messages.append('%s: %s' % (rec.display_name, rec.last_sync_message or 'Fingerprint pulled.'))
        return self._notification_action('Pull Fingerprint', '; '.join(messages[:5]), notification_type='success')

    def _get_source_device(self, raise_error=False):
        self.ensure_one()
        device = self.source_device_id
        if device and device.enabled:
            return device

        msg = 'Please select an enabled Source Device before pulling fingerprint.'
        if raise_error:
            raise UserError(msg)
        return self.env['entry.control.device'].browse()

    def _pull_from_device(self, raise_error=False):
        self.ensure_one()

        if self.biometric_type != 'fingerprint':
            msg = 'Only fingerprint is supported in phase 1.'
            self._write_result('failed', msg, False)
            if raise_error:
                raise UserError(msg)
            return False

        device = self._get_source_device()
        if not device:
            msg = 'Please select an enabled Source Device before pulling fingerprint.'
            self._write_result('failed', msg, False)
            if raise_error:
                raise UserError(msg)
            return False

        result = device._call_agent_download_fingerprint(self.user_id, self.finger_index, raise_error=raise_error)
        if not result:
            msg = device.last_biometric_message or 'Download fingerprint failed.'
            self._write_result('failed', msg, device)
            if raise_error:
                raise UserError(msg)
            return False

        self.write({
            'template_data': result.get('templateData') or '',
            'template_length': int(result.get('templateLength') or 0),
            'flag': int(result.get('flag') or 1),
            'algorithm': device._map_fingerprint_algorithm(result.get('algorithm') or 'ZKFinger10'),
            'source_device_id': device.id,
            'sync_state': 'pulled',
            'last_sync_at': fields.Datetime.now(),
            'last_sync_device_id': device.id,
            'last_sync_message': 'Pulled fingerprint from %s. Length=%s' % (device.display_name, result.get('templateLength') or 0),
        })
        return True

    def _write_result(self, state, message, device):
        vals = {
            'sync_state': state,
            'last_sync_at': fields.Datetime.now(),
            'last_sync_message': message,
        }
        if device:
            vals['last_sync_device_id'] = device.id
        self.write(vals)
