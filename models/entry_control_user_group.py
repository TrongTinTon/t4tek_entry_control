from odoo import api, fields, models
from odoo.exceptions import UserError


class EntryControlUserGroup(models.Model):
    _name = 'entry.control.user.group'
    _description = 'Entry Control User Group'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    sync_enabled = fields.Boolean(string='Allow Sync', default=True)
    note = fields.Text()

    user_ids = fields.Many2many(
        'entry.control.user',
        'entry_control_user_group_rel',
        'group_id',
        'user_id',
        string='Global Device Users',
    )
    user_count = fields.Integer(string='Users', compute='_compute_user_count')

    policy_ids = fields.One2many('entry.control.sync.policy', 'user_group_id', string='Sync Policies')

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

    @api.depends('user_ids')
    def _compute_user_count(self):
        for rec in self:
            rec.user_count = len(rec.user_ids)

    def action_sync_group(self):
        Policy = self.env['entry.control.sync.policy'].sudo()
        total_policies = 0
        for rec in self:
            policies = Policy.search([
                ('active', '=', True),
                ('sync_enabled', '=', True),
                ('user_group_id', '=', rec.id),
            ])
            if not policies:
                raise UserError('No active sync policy found for this user group.')
            total_policies += len(policies)
            for policy in policies:
                policy._sync_policy(raise_error=True)
        return self._notification_action('Sync User Group', 'Executed %s policy sync(s) for %s user group(s).' % (total_policies, len(self)), notification_type='success')
