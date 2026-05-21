from odoo import api, fields, models
from odoo.exceptions import UserError


class EntryControlDeviceGroup(models.Model):
    _name = 'entry.control.device.group'
    _description = 'Entry Control Device Group'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    sync_enabled = fields.Boolean(string='Allow Sync', default=True)
    note = fields.Text()

    device_ids = fields.Many2many(
        'entry.control.device',
        'entry_control_device_group_rel',
        'group_id',
        'device_id',
        string='Devices',
    )
    device_count = fields.Integer(string='Devices', compute='_compute_counts')
    controller_ids = fields.Many2many('entry.control.controller', string='Controllers', compute='_compute_counts')
    controller_count = fields.Integer(string='Controllers', compute='_compute_counts')

    policy_ids = fields.One2many('entry.control.sync.policy', 'device_group_id', string='Sync Policies')

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

    @api.depends('device_ids', 'device_ids.controller_id')
    def _compute_counts(self):
        for rec in self:
            rec.device_count = len(rec.device_ids)
            controllers = rec.device_ids.mapped('controller_id')
            rec.controller_ids = controllers
            rec.controller_count = len(controllers)

    def action_sync_group(self):
        Policy = self.env['entry.control.sync.policy'].sudo()
        total_policies = 0
        for rec in self:
            policies = Policy.search([
                ('active', '=', True),
                ('sync_enabled', '=', True),
                ('device_group_id', '=', rec.id),
            ])
            if not policies:
                raise UserError('No active sync policy found for this device group.')
            total_policies += len(policies)
            for policy in policies:
                policy._sync_policy(raise_error=True)
        return self._notification_action('Sync Device Group', 'Executed %s policy sync(s) for %s device group(s).' % (total_policies, len(self)), notification_type='success')
