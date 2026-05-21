from odoo import api, fields, models, _


class EntryControlDevice(models.Model):
    _name = "entry.control.device"
    _description = "Entry Control Device"
    _order = "last_seen_at desc, id desc"

    active = fields.Boolean(default=True, index=True)
    controller_id = fields.Many2one("entry.control.controller", required=True, ondelete="cascade", index=True)
    controller_code = fields.Char(related="controller_id.controller_code", store=True, index=True)
    device_code = fields.Char(required=True, index=True, copy=False)
    name = fields.Char(string="Device Name", required=True)
    device_name = fields.Char(string="Device Name (reported)")
    device_type = fields.Selection([
        ("zkteco", "ZKTeco"),
        ("zk_access", "ZKTeco Access/Attendance"),
        ("senseface", "SenseFace"),
        ("camera", "Camera"),
        ("other", "Other"),
    ], default="senseface", required=True)
    ip_address = fields.Char()
    port = fields.Integer(default=4370)
    machine_no = fields.Integer(default=1)
    comm_mode = fields.Selection([("tcp", "TCP/IP")], default="tcp")
    serial_number = fields.Char(index=True)
    model = fields.Char()
    firmware_version = fields.Char()
    is_online = fields.Boolean(default=False, index=True)
    last_seen_at = fields.Datetime(readonly=True)
    last_online_at = fields.Datetime(readonly=True)
    last_offline_at = fields.Datetime(readonly=True)
    last_diagnostic_at = fields.Datetime(readonly=True)
    last_user_pull_at = fields.Datetime(readonly=True)
    last_attendance_pull_at = fields.Datetime(readonly=True)
    last_fingerprint_pull_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    assignment_count = fields.Integer(compute="_compute_assignment_count")

    _sql_constraints = [
        ("device_code_controller_unique", "unique(controller_id, device_code)", "Device code must be unique per controller."),
    ]

    @api.depends("device_code")
    def _compute_assignment_count(self):
        Assignment = self.env["entry.control.assignment"].sudo()
        for rec in self:
            rec.assignment_count = Assignment.search_count([("device_id", "=", rec.id)])

    def action_auto_sync_all_users(self):
        total = 0
        User = self.env["entry.control.user"].sudo()
        users = User.search([])
        for device in self:
            if not device.active or device.controller_id.blocked or not device.controller_id.approved or device.controller_id.registration_status != "approved":
                continue
            for user in users:
                if user.is_deleted:
                    cmd_type = "delete_user"
                elif not user.is_active:
                    cmd_type = "disable_user"
                else:
                    # A device report means this is a sync target. For active users,
                    # the safe first command is create_user, not update_user.
                    cmd_type = "create_user"
                total += user.action_auto_sync_to_all_devices(command_type=cmd_type, only_device=device)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Auto sync queued"),
                "message": _("Queued %s command(s) for selected device(s).") % total,
                "type": "success",
                "sticky": False,
            },
        }


    @api.model
    def _normalize_device_type(self, value):
        value = (value or "zkteco").strip().lower()
        aliases = {
            "zk": "zkteco",
            "zk_access": "zk_access",
            "zkteco": "zkteco",
            "senseface": "senseface",
            "iface": "senseface",
            "camera": "camera",
        }
        return aliases.get(value, "other")

    @api.model
    def upsert_from_payload(self, controller, payload):
        code = (payload.get("device_code") or payload.get("code") or "").strip()
        if not code:
            return self.browse()
        vals = {
            "controller_id": controller.id,
            "device_code": code,
            "name": payload.get("device_name") or payload.get("name") or code,
            "device_name": payload.get("device_name") or payload.get("name") or code,
            "device_type": self._normalize_device_type(payload.get("device_type") or payload.get("type") or "zkteco"),
            "ip_address": payload.get("ip_address"),
            "port": int(payload.get("port") or 4370),
            "machine_no": int(payload.get("machine_no") or 1),
            "serial_number": payload.get("serial_number"),
            "model": payload.get("model"),
            "firmware_version": payload.get("firmware_version"),
            "active": payload.get("is_active", True),
            "is_online": bool(payload.get("is_online", False)),
            "last_seen_at": fields.Datetime.now(),
            "last_error": payload.get("last_error"),
        }
        if vals["is_online"]:
            vals["last_online_at"] = fields.Datetime.now()
        else:
            vals["last_offline_at"] = fields.Datetime.now()

        device = self.sudo().search([("controller_id", "=", controller.id), ("device_code", "=", code)], limit=1)
        was_existing = bool(device)
        was_active = bool(device.active) if device else False
        if device:
            device.sudo().write(vals)
        else:
            device = self.sudo().create(vals)

        # Device report is inventory/status only. A Controller that adds a new
        # local device should apply cached desired state on the Controller side.
        return device
