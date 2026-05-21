import hashlib
import secrets
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EntryControlController(models.Model):
    _name = "entry.control.controller"
    _description = "Entry Control Controller"
    _order = "last_seen_at desc, id desc"

    controller_code = fields.Char(required=True, index=True, copy=False)
    name = fields.Char(string="Controller Name", required=True)
    controller_name = fields.Char(string="Controller Name (reported)")
    server_base_url = fields.Char()
    public_key_pem = fields.Text()
    private_key_ref = fields.Char(readonly=True)
    key_fingerprint = fields.Char(index=True)
    registration_status = fields.Selection([
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("blocked", "Blocked"),
        ("rejected", "Rejected"),
        ("revoked", "Revoked"),
    ], default="approved", required=True, index=True)
    approved = fields.Boolean(default=True, index=True)
    blocked = fields.Boolean(default=False, index=True)
    token_hash = fields.Char(copy=False, readonly=True)
    token_hint = fields.Char(copy=False, readonly=True)
    token_issued_at = fields.Datetime(copy=False, readonly=True)
    token_expires_at = fields.Datetime(copy=False, readonly=True)
    last_login_at = fields.Datetime(readonly=True)
    last_auth_at = fields.Datetime(readonly=True)
    last_seen_at = fields.Datetime(readonly=True)
    last_hello_at = fields.Datetime(readonly=True)
    last_device_report_at = fields.Datetime(readonly=True)
    last_manifest_pull_at = fields.Datetime(string="Last Manifest Pull", readonly=True)
    last_sync_version = fields.Integer(string="Last Sync Version", default=0, readonly=True, index=True)
    app_version = fields.Char(readonly=True)
    machine_name = fields.Char(readonly=True)
    local_ip = fields.Char(readonly=True)
    last_error = fields.Text(readonly=True)
    device_count = fields.Integer(compute="_compute_counts")
    pending_command_count = fields.Integer(string="Pending Commands (deprecated)", compute="_compute_counts")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("controller_code_unique", "unique(controller_code)", "Controller code must be unique."),
    ]

    @api.depends("controller_code")
    def _compute_counts(self):
        Device = self.env["entry.control.device"].sudo()
        for rec in self:
            rec.device_count = Device.search_count([("controller_id", "=", rec.id), ("active", "=", True)])
            rec.pending_command_count = 0

    @api.model
    def _hash_token(self, token):
        token = token or ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @api.model
    def _new_token(self):
        return secrets.token_urlsafe(48)

    def check_token(self, token):
        self.ensure_one()
        return bool(token and self.token_hash and self._hash_token(token) == self.token_hash)

    def issue_runtime_token(self):
        """Issue a runtime token for the Controller API client.

        The token is returned only in this API response. Odoo stores only
        SHA256(token). The Controller does not need any token configured
        manually; it asks /api/entry_control/v1/auth/token after approval.
        """
        self.ensure_one()
        if self.blocked or self.registration_status == "blocked" or not self.approved:
            raise UserError(_("Controller is blocked or not approved."))
        token = self._new_token()
        now = fields.Datetime.now()
        ttl = int(self.env["ir.config_parameter"].sudo().get_param("entry_control.controller_token_ttl_seconds", "3600") or 3600)
        expires_at = now + timedelta(seconds=max(300, ttl))
        self.sudo().write({
            "token_hash": self._hash_token(token),
            "token_hint": "%s...%s" % (token[:8], token[-6:]),
            "token_issued_at": now,
            "token_expires_at": expires_at,
            "last_login_at": now,
            "last_auth_at": now,
            "last_seen_at": now,
            "last_error": False,
        })
        return token

    def action_approve(self):
        # Backward-compatible alias.  The current workflow auto-approves from
        # /hello; administrators normally only use Block / Unblock.
        return self.action_unblock()

    def action_block(self):
        for rec in self:
            rec.write({
                "approved": False,
                "blocked": True,
                "registration_status": "blocked",
                "token_hash": False,
                "token_hint": False,
                "token_issued_at": False,
                "token_expires_at": False,
                "last_error": _("Controller blocked by administrator."),
            })
        return True

    def action_unblock(self):
        for rec in self:
            rec.write({
                "approved": True,
                "blocked": False,
                "registration_status": "approved",
                "last_error": False,
            })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Controller active"),
                "message": _("Controller is active. It can request a runtime token through the auth API."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_regenerate_token(self):
        self.ensure_one()
        if self.blocked or not self.approved or self.registration_status != "approved":
            raise UserError(_("Unblock/activate the controller before resetting the runtime token."))
        self.write({"token_hash": False, "token_hint": False, "token_issued_at": False, "token_expires_at": False, "last_auth_at": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Runtime token reset"),
                "message": _("The old runtime token has been invalidated. The Controller will request a new one through the auth API."),
                "type": "warning",
                "sticky": False,
            },
        }

    def action_revoke(self):
        # Kept for compatibility with older records/buttons.  In the simplified
        # workflow this is equivalent to Block.
        return self.action_block()

    def action_auto_sync_all_users(self):
        # Desired-state sync is automatic. This button is kept only for backward compatibility.
        total = 0
        User = self.env["entry.control.user"].sudo()
        for user in User.search([]):
            if user.is_deleted:
                cmd_type = "delete_user"
            elif not user.is_active:
                cmd_type = "disable_user"
            else:
                cmd_type = "create_user"
            total += 0
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Desired-state sync"),
                "message": _("No command rows were queued. Controllers will pull the desired-state manifest automatically."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_mark_pending(self):
        for rec in self:
            rec.write({"approved": False, "blocked": False, "registration_status": "pending"})
        return True

    @api.model
    def upsert_from_hello(self, payload, mark_hello=True):
        code = (payload.get("controller_code") or "").strip().upper()
        if not code:
            raise UserError(_("controller_code is required."))
        vals = {
            "controller_code": code,
            "name": payload.get("controller_name") or code,
            "controller_name": payload.get("controller_name") or code,
            "server_base_url": payload.get("server_base_url"),
            "public_key_pem": payload.get("public_key_pem"),
            "key_fingerprint": payload.get("key_fingerprint"),
            "last_seen_at": fields.Datetime.now(),
        }
        if mark_hello:
            vals.update({
                "last_hello_at": fields.Datetime.now(),
                "app_version": payload.get("app_version") or payload.get("version"),
                "machine_name": payload.get("machine_name") or payload.get("machineName"),
                "local_ip": payload.get("local_ip") or payload.get("localIp"),
            })
        Controller = self.sudo()
        controller = Controller.search([("controller_code", "=", code)], limit=1)
        if not controller:
            controller = Controller.search([("controller_code", "=ilike", code)], order="id asc", limit=1)
        if controller:
            update_vals = {k: v for k, v in vals.items() if v is not None}
            # Normalize old lowercase/mixed-case records to the stable uppercase code.
            if controller.controller_code != code:
                update_vals["controller_code"] = code
            if not controller.blocked and controller.registration_status not in ("blocked", "revoked", "rejected"):
                update_vals.update({"approved": True, "blocked": False, "registration_status": "approved", "last_error": False})
            controller.sudo().write(update_vals)
        else:
            # New Controller is active immediately.  Admin can block it later.
            vals.update({"approved": True, "blocked": False, "registration_status": "approved", "last_error": False})
            controller = Controller.create(vals)
        return controller
