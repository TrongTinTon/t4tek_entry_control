from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EntryControlUser(models.Model):
    _name = "entry.control.user"
    _description = "Entry Control Device User"
    _order = "write_date desc, id desc"

    employee_id = fields.Many2one("hr.employee", string="Employee", ondelete="set null", index=True)
    pin = fields.Char(required=True, index=True, copy=False, help="Device PIN. When Employee is selected, this value is referenced from hr.employee.pin.")
    name = fields.Char(required=True)
    password = fields.Char()
    card_no = fields.Char(index=True)
    privilege = fields.Integer(default=0)
    group_no = fields.Integer(default=1)
    timezone_no = fields.Integer(default=1)
    is_active = fields.Boolean(default=True, index=True)
    is_deleted = fields.Boolean(default=False, index=True)
    fingerprint_ids = fields.One2many("entry.control.fingerprint", "user_id", string="Fingerprints")
    fingerprint_count = fields.Integer(compute="_compute_fingerprint_count")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("pin_unique", "unique(pin)", "PIN must be unique."),
        ("employee_unique", "unique(employee_id)", "Only one Device User can be linked to one Employee."),
    ]

    _SYNC_WATCHED_FIELDS = {
        "employee_id",
        "pin",
        "name",
        "password",
        "card_no",
        "privilege",
        "group_no",
        "timezone_no",
        "is_active",
        "is_deleted",
    }

    @api.depends("fingerprint_ids")
    def _compute_fingerprint_count(self):
        for rec in self:
            rec.fingerprint_count = len(rec.fingerprint_ids)

    @api.model
    def _employee_pin_field(self):
        Employee = self.env["hr.employee"]
        return "pin" if "pin" in Employee._fields else False

    @api.model
    def _get_employee_pin(self, employee):
        if not employee:
            return ""
        field_name = self._employee_pin_field()
        if not field_name:
            raise UserError(_("hr.employee does not have field 'pin'. Please enable/configure Employee PIN before generating Device Users."))
        pin = str(employee[field_name] or "").strip()
        if not pin:
            raise UserError(_("Employee %s does not have a PIN. Please fill Employee PIN first.") % employee.display_name)
        return pin

    def _prepare_vals_from_employee(self, vals):
        vals = dict(vals or {})
        if vals.get("employee_id"):
            employee = self.env["hr.employee"].sudo().browse(vals["employee_id"]).exists()
            if employee:
                vals["pin"] = self._get_employee_pin(employee)
                vals.setdefault("name", employee.name or employee.display_name or vals["pin"])
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared = [self._prepare_vals_from_employee(vals) for vals in vals_list]
        return super().create(prepared)

    def write(self, vals):
        vals = self._prepare_vals_from_employee(vals)
        return super().write(vals)

    @api.constrains("employee_id", "pin")
    def _check_employee_pin_reference(self):
        for rec in self.filtered("employee_id"):
            expected = rec._get_employee_pin(rec.employee_id)
            if str(rec.pin or "").strip() != expected:
                raise ValidationError(_("Device User PIN must reference Employee PIN. Employee %s currently has PIN %s.") % (rec.employee_id.display_name, expected))

    def _has_create_command_log(self):
        return False

    def _command_type_for_write(self, vals):
        self.ensure_one()
        old_active = bool(self.is_active)
        old_deleted = bool(self.is_deleted)
        new_active = bool(vals.get("is_active", self.is_active))
        new_deleted = bool(vals.get("is_deleted", self.is_deleted))
        if new_deleted:
            return "delete_user"
        if old_deleted and not new_deleted and new_active:
            return "enable_user"
        if not new_active:
            return "disable_user"
        if not old_active and new_active:
            return "enable_user"
        # Desired-state sync uses final user state. The returned value is kept
        # only for old compatibility callers and does not create server commands.
        if new_active and not new_deleted and not self._has_create_command_log():
            return "create_user"
        return "update_user"

    def _auto_command_type(self, preferred=None):
        self.ensure_one()
        if preferred:
            return preferred
        if self.is_deleted:
            return "delete_user"
        if not self.is_active:
            return "disable_user"
        return "update_user"

    def _payload(self, command_type=None):
        self.ensure_one()
        command_type = command_type or self._auto_command_type()
        payload = {
            "command_type": command_type,
            "pin": self.pin,
            "employee_id": self.employee_id.id if self.employee_id else False,
            "employee_name": self.employee_id.display_name if self.employee_id else "",
            "name": self.name,
            "card_no": self.card_no or "",
            "cardNo": self.card_no or "",
            "privilege": self.privilege or 0,
            "group_no": self.group_no or 1,
            "groupNo": self.group_no or 1,
            "timezone_no": self.timezone_no or 1,
            "timezoneNo": self.timezone_no or 1,
            "is_active": bool(self.is_active),
            "isActive": bool(self.is_active),
            "is_deleted": bool(self.is_deleted),
            "isDeleted": bool(self.is_deleted),
            "target_scope": "controller_all_devices",
            "apply_to_all_devices": True,
        }
        if command_type == "create_user" or self.password:
            payload["password"] = self.password or ""
            payload["password_provided"] = bool(self.password)
        return payload

    def action_queue_command_log(self, command_type=None, only_controller=None):
        # Deprecated no-op: Controllers pull desired state through /sync/manifest.
        return 0

    def action_auto_sync_to_all_devices(self, command_type=None, only_controller=None, only_device=None):
        # No-op: Controllers pull desired state through /sync/manifest.
        return 0

    def action_open_generate_from_employees(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Generate Device Users from Employees"),
            "res_model": "entry.control.generate.users.wizard",
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context or {}),
        }

    def action_queue_full_create_log(self):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Desired-state sync"),
                "message": _("Controllers will pull the latest desired state automatically."),
                "type": "info",
                "sticky": False,
            },
        }

    def unlink(self):
        if self.env.context.get("force_entry_control_unlink"):
            return super().unlink()
        for rec in self:
            rec.write({"is_deleted": True, "is_active": False})
        return True

    # Backward-compatible button methods. Views no longer expose manual sync buttons.
    def action_queue_create_update(self):
        return self.action_queue_command_log(command_type="update_user")

    def action_queue_delete(self):
        self.write({"is_deleted": True, "is_active": False})
        return True

    def action_queue_disable(self):
        self.write({"is_active": False})
        return True

    def action_queue_enable(self):
        self.write({"is_active": True, "is_deleted": False})
        return True


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _entry_control_device_user_vals(self):
        self.ensure_one()
        pin = str(getattr(self, "pin", "") or "").strip() if "pin" in self._fields else ""
        if not pin:
            return False
        return {
            "employee_id": self.id,
            "pin": pin,
            "name": self.name or self.display_name or pin,
            "is_active": bool(getattr(self, "active", True)),
            "is_deleted": False,
        }

    def _entry_control_sync_device_user_from_employee(self):
        """Auto-create/update Device User from Employee PIN.

        This replaces the old manual "Generate from Employees" workflow:
        - When a new Employee has PIN, create exactly one Device User.
        - When Employee PIN/name/active changes, update the linked Device User.
        - If there is already a Device User with the same PIN, link it to the Employee
          when it is not linked to another Employee.
        """
        DeviceUser = self.env["entry.control.user"].sudo()
        for employee in self.sudo():
            vals = employee._entry_control_device_user_vals()
            if not vals:
                continue
            user = DeviceUser.search([("employee_id", "=", employee.id)], limit=1)
            if not user:
                existing_by_pin = DeviceUser.search([("pin", "=", vals["pin"])], limit=1)
                if existing_by_pin:
                    if existing_by_pin.employee_id and existing_by_pin.employee_id.id != employee.id:
                        # Avoid breaking the one Employee = one Device User rule.
                        continue
                    user = existing_by_pin
            if user:
                write_vals = {
                    "employee_id": employee.id,
                    "pin": vals["pin"],
                    "name": vals["name"],
                    "is_active": vals["is_active"],
                    "is_deleted": False,
                }
                user.write(write_vals)
            else:
                DeviceUser.create(vals)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        # Do not create or modify res.partner here. This module only mirrors
        # Employee PIN data into entry.control.user. Partner role rules belong
        # to the Contacts/partner customization, not Attendance Gateway.
        employees = super().create(vals_list)
        if "pin" in self._fields:
            employees._entry_control_sync_device_user_from_employee()
        return employees

    def write(self, vals):
        watched = {"pin", "name", "active"}
        should_sync = bool(watched.intersection(vals.keys()))
        result = super().write(vals)
        if should_sync and "pin" in self._fields:
            self._entry_control_sync_device_user_from_employee()
        return result
