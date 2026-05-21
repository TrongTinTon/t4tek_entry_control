from odoo import api, fields, models


class EntryControlCommand(models.Model):
    _name = "entry.control.command"
    _description = "Entry Control Device User Command Log"
    _order = "id desc"

    # Legacy nullable fields kept only to make upgrades from older builds safe.
    # They are not used by the current workflow and are not shown in views/API.
    controller_id = fields.Many2one("entry.control.controller", string="Legacy Controller", ondelete="set null", index=True, readonly=True)
    controller_code = fields.Char(string="Legacy Controller Code", index=True, readonly=True)
    user_id = fields.Many2one("entry.control.user", string="Device User", ondelete="set null", index=True)
    pin = fields.Char(index=True)
    command_type = fields.Selection([
        ("create_user", "Create User"),
        ("update_user", "Update User"),
        ("delete_user", "Delete User"),
        ("disable_user", "Disable User"),
        ("enable_user", "Enable User"),
        ("push_fingerprint", "Push Fingerprint"),
        ("delete_fingerprint", "Delete Fingerprint"),
    ], required=True, index=True)
    payload = fields.Json(required=True, default=dict)
    odoo_command_id = fields.Integer(string="Command Row ID", compute="_compute_odoo_command_id")

    def _compute_odoo_command_id(self):
        for rec in self:
            rec.odoo_command_id = rec.id or 0

    @api.model
    def create_command(self, *args, **kwargs):
        """Append one global command log row from a Device User change.

        Final rule requested by customer:
        - Device Users are the business data to synchronize.
        - Command Log is generated from Device User/Fingerprint changes.
        - Command Log is NOT scoped to Controller.
        - Every Controller keeps its own local last_command_id cursor and pulls
          global command rows with id > last_command_id.
        - Execution/retry state is stored in the Controller local DB.

        Backward compatibility: older code may still call this method as
        create_command(controller, command_type, payload, user=..., device=...).
        The controller/device/dedupe arguments are ignored intentionally.
        """
        user = kwargs.get("user")
        command_type = kwargs.get("command_type")
        payload = kwargs.get("payload")

        clean_args = list(args)
        if clean_args and hasattr(clean_args[0], "_name") and getattr(clean_args[0], "_name", "") == "entry.control.controller":
            clean_args.pop(0)  # legacy controller argument; no longer part of Command Log
        if command_type is None and clean_args:
            command_type = clean_args.pop(0)
        if payload is None and clean_args:
            payload = clean_args.pop(0)
        if user is None and clean_args and hasattr(clean_args[0], "_name") and getattr(clean_args[0], "_name", "") == "entry.control.user":
            user = clean_args.pop(0)

        payload = dict(payload or {})
        vals = {
            "command_type": command_type,
            "payload": payload,
            "pin": user.pin if user else payload.get("pin"),
        }
        if user:
            vals["user_id"] = user.id
        return self.sudo().create(vals)

    @api.model
    def create_global_command(self, command_type, payload, user=None):
        return self.create_command(command_type=command_type, payload=payload, user=user)
