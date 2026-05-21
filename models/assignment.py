from odoo import api, fields, models


class EntryControlAssignment(models.Model):
    _name = "entry.control.assignment"
    _description = "Entry Control User Device Assignment"
    _order = "write_date desc, id desc"

    user_id = fields.Many2one("entry.control.user", required=True, ondelete="cascade", index=True)
    pin = fields.Char(related="user_id.pin", store=True, index=True)
    device_id = fields.Many2one("entry.control.device", required=True, ondelete="cascade", index=True)
    device_code = fields.Char(related="device_id.device_code", store=True, index=True)
    controller_id = fields.Many2one(related="device_id.controller_id", store=True, index=True)
    desired_state = fields.Selection([
        ("present", "Present"),
        ("deleted", "Deleted"),
        ("disabled", "Disabled"),
    ], default="present", required=True, index=True)
    source = fields.Selection([
        ("manual", "Manual"),
        ("auto", "Auto Sync"),
        ("odoo", "Odoo"),
        ("import", "Import"),
        ("api", "API"),
        ("employee", "Employee"),
    ], default="manual", required=True)
    assigned_at = fields.Datetime(default=fields.Datetime.now)
    removed_at = fields.Datetime()
    note = fields.Text()

    _sql_constraints = [
        ("assignment_unique", "unique(user_id, device_id)", "User is already assigned to this device."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def write(self, vals):
        return super().write(vals)

    def _queue_assignment_command(self, command_type):
        # No-op: assignment changes are picked up by desired-state manifest.
        return 0
