from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EntryControlGenerateUsersWizard(models.TransientModel):
    _name = "entry.control.generate.users.wizard"
    _description = "Generate Entry Control Users from Employees"

    employee_ids = fields.Many2many(
        "hr.employee",
        string="Employees",
        help="Leave empty to generate from all active employees.",
    )
    pin_source = fields.Selection([
        ("pin", "Employee PIN Code / pin"),
    ], default="pin", required=True)
    card_source = fields.Selection([
        ("none", "None"),
        ("barcode", "Employee Badge / barcode"),
        ("identification_id", "Identification No."),
        ("registration_number", "Registration Number"),
    ], default="barcode", required=True)
    update_existing = fields.Boolean(default=True)
    active_employees_only = fields.Boolean(default=True)
    result_message = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if self.env.context.get("active_model") == "hr.employee" and self.env.context.get("active_ids"):
            vals["employee_ids"] = [(6, 0, self.env.context.get("active_ids"))]
        return vals

    def _clean_value(self, value):
        if value is None or value is False:
            return ""
        return str(value).replace("\x00", "").strip()

    def _read_employee_field(self, employee, field_name):
        if field_name == "id":
            return str(employee.id)
        if field_name not in employee._fields:
            return ""
        return self._clean_value(employee[field_name])

    def _get_pin(self, employee):
        if "pin" not in employee._fields:
            raise UserError(_("Employee model does not have field 'pin'. Please enable/configure Employee PIN first."))
        return self._read_employee_field(employee, "pin")

    def _get_card_no(self, employee):
        if self.card_source == "none":
            return ""
        return self._read_employee_field(employee, self.card_source)

    def _get_employees(self):
        self.ensure_one()
        if self.employee_ids:
            return self.employee_ids
        domain = []
        if self.active_employees_only and "active" in self.env["hr.employee"]._fields:
            domain.append(("active", "=", True))
        return self.env["hr.employee"].search(domain)

    def action_generate(self):
        self.ensure_one()
        User = self.env["entry.control.user"].sudo()

        employees = self._get_employees()
        if not employees:
            raise UserError(_("No employees found."))

        created = 0
        updated = 0
        skipped = []

        for employee in employees:
            pin = self._get_pin(employee)
            if not pin:
                skipped.append("%s: missing PIN source" % employee.display_name)
                continue

            card_no = self._get_card_no(employee)
            vals = {
                "employee_id": employee.id,
                "pin": pin,
                "name": employee.name or employee.display_name or pin,
                "card_no": card_no,
                "privilege": 0,
                "group_no": 1,
                "timezone_no": 1,
                "is_active": True,
                "is_deleted": False,
            }

            user = User.search([("employee_id", "=", employee.id)], limit=1)
            if not user:
                user = User.search([("pin", "=", pin)], limit=1)

            if user:
                if not self.update_existing:
                    skipped.append("%s: Device User already exists for PIN %s" % (employee.display_name, pin))
                    continue
                if user.pin and user.pin != pin:
                    skipped.append("%s: existing Device User has different PIN %s, expected %s" % (employee.display_name, user.pin, pin))
                    continue
                user.write(vals)
                updated += 1
            else:
                User.create(vals)
                created += 1

        lines = [
            _("Generated Device Users from Employees."),
            _("Created: %s") % created,
            _("Updated: %s") % updated,
            _("Controllers will pick up generated Device Users through desired-state manifest sync."),
            _("Skipped: %s") % len(skipped),
        ]
        if skipped:
            lines.append("")
            lines.append(_("Skipped details:"))
            lines.extend(skipped[:50])

        self.write({"result_message": "\n".join(lines)})
        return {
            "type": "ir.actions.act_window",
            "name": _("Generate Device Users from Employees"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
