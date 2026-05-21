import uuid
from odoo import api, fields, models, _


def _short_value(value, left=12, right=8):
    value = value or ""
    if len(value) <= left + right + 3:
        return value
    return "%s...%s" % (value[:left], value[-right:])


class EntryControlFingerprint(models.Model):
    _name = "entry.control.fingerprint"
    _description = "Entry Control Fingerprint Master"
    _order = "write_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    fingerprint_uid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, index=True)
    user_id = fields.Many2one("entry.control.user", string="Device User", required=True, ondelete="cascade", index=True)
    pin = fields.Char(related="user_id.pin", store=True, index=True)
    finger_index = fields.Integer(default=0, required=True, index=True)
    template_version = fields.Char(default="", string="Template Version")
    template_base64 = fields.Text(string="Active Template Base64", readonly=True)
    template_hash = fields.Char(index=True, readonly=True)
    template_hash_short = fields.Char(string="Template Hash", compute="_compute_hash_short")
    template_length = fields.Integer(readonly=True)
    source_device_id = fields.Many2one("entry.control.device", string="Source Device", ondelete="set null")
    source_device_code = fields.Char(index=True)
    status = fields.Selection([
        ("pending_review", "Pending Review"),
        ("active", "Active"),
        ("disabled", "Disabled"),
        ("deleted", "Deleted"),
        ("rejected", "Rejected"),
    ], default="active", required=True, index=True)
    server_version = fields.Integer(default=1, index=True)
    last_collected_at = fields.Datetime()
    last_pushed_at = fields.Datetime()
    last_deleted_at = fields.Datetime()

    pending_template_base64 = fields.Text(string="Pending Template Base64", readonly=True)
    pending_template_hash = fields.Char(readonly=True)
    pending_template_hash_short = fields.Char(string="Pending Template Hash", compute="_compute_hash_short")
    pending_template_length = fields.Integer(readonly=True)
    pending_source_device_id = fields.Many2one("entry.control.device", ondelete="set null", readonly=True)
    pending_source_device_code = fields.Char(readonly=True)
    pending_collected_at = fields.Datetime(readonly=True)

    note = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("fingerprint_uid_unique", "unique(fingerprint_uid)", "Fingerprint UID must be unique."),
        ("fingerprint_unique_user_index", "unique(user_id, finger_index, template_version)", "A Device User can only have one active fingerprint master per finger index/template version."),
    ]


    @api.depends("template_hash", "pending_template_hash")
    def _compute_hash_short(self):
        for rec in self:
            rec.template_hash_short = _short_value(rec.template_hash)
            rec.pending_template_hash_short = _short_value(rec.pending_template_hash)

    @api.depends("pin", "finger_index", "template_version", "status")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s - Finger %s (%s)" % (rec.pin or "", rec.finger_index, rec.template_version or "unknown")

    def _payload(self, command_type="push_fingerprint", target_device=None):
        self.ensure_one()
        target_device_code = target_device.device_code if target_device else ""
        payload = {
            "command_id": str(uuid.uuid4()),
            "command_type": command_type,
            "fingerprint_uid": self.fingerprint_uid,
            "server_fingerprint_id": self.id,
            "server_version": self.server_version,
            "pin": self.pin,
            "finger_index": self.finger_index,
            "template_version": self.template_version or "",
            "template_base64": self.template_base64 or "",
            "template_hash": self.template_hash or "",
            "template_length": self.template_length or 0,
            "status": self.status,
            "target_scope": "device" if target_device_code else "controller_all_devices",
            "apply_to_all_devices": False if target_device_code else True,
            "deviceCodes": [target_device_code] if target_device_code else [],
        }
        if target_device_code:
            payload.update({
                "device_code": target_device_code,
                "deviceCode": target_device_code,
                "target_device_code": target_device_code,
                "targetDeviceCode": target_device_code,
            })
        return payload

    def queue_push_to_devices(self, only_device=None):
        # Controllers detect fingerprint_set_hash changes from /sync/manifest.
        return 0

    def queue_delete_to_devices(self, only_device=None):
        # Desired-state manifest marks deleted/disabled fingerprint state.
        return 0

    def action_approve_pending(self):
        for rec in self:
            if not rec.pending_template_base64 or not rec.pending_template_hash:
                continue
            rec.write({
                "template_base64": rec.pending_template_base64,
                "template_hash": rec.pending_template_hash,
                "template_length": rec.pending_template_length or 0,
                "source_device_id": rec.pending_source_device_id.id if rec.pending_source_device_id else False,
                "source_device_code": rec.pending_source_device_code,
                "last_collected_at": rec.pending_collected_at or fields.Datetime.now(),
                "pending_template_base64": False,
                "pending_template_hash": False,
                "pending_template_length": 0,
                "pending_source_device_id": False,
                "pending_source_device_code": False,
                "pending_collected_at": False,
                "status": "active",
                "server_version": (rec.server_version or 0) + 1,
            })
            rec.queue_push_to_devices()
        return True

    def action_reject_pending(self):
        self.write({
            "pending_template_base64": False,
            "pending_template_hash": False,
            "pending_template_length": 0,
            "pending_source_device_id": False,
            "pending_source_device_code": False,
            "pending_collected_at": False,
            "status": "active",
        })
        return True

    def action_push_to_devices(self):
        total = self.queue_push_to_devices()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Fingerprint sync"), "message": _("Fingerprint desired state will be pulled automatically by Controllers."), "type": "success", "sticky": False},
        }

    def action_disable(self):
        for rec in self:
            rec.write({"status": "disabled", "server_version": (rec.server_version or 0) + 1})
            # Policy: disable means remove the biometric template from devices while
            # preserving the server master in Odoo.
            rec.queue_delete_to_devices()
        return True

    def action_delete_fingerprint(self):
        for rec in self:
            rec.write({"status": "deleted", "last_deleted_at": fields.Datetime.now(), "server_version": (rec.server_version or 0) + 1})
            rec.queue_delete_to_devices()
        return True

    @api.model
    def _find_device(self, controller, device_code):
        if not device_code:
            return self.env["entry.control.device"].browse()
        return self.env["entry.control.device"].sudo().search([
            ("controller_id", "=", controller.id),
            ("device_code", "=", device_code),
        ], limit=1)

    @api.model
    def ingest_collected_from_event(self, event):
        payload = event.payload or {}
        pin = payload.get("pin")
        if not pin:
            return False
        user = self.env["entry.control.user"].sudo().search([("pin", "=", pin)], limit=1)
        if not user:
            # Unknown user is handled by conflict/event flow. Do not create biometric master without a Device User.
            return False

        finger_index = int(payload.get("finger_index") or payload.get("fingerIndex") or 0)
        template_version = payload.get("template_version") or payload.get("templateVersion") or ""
        template_base64 = payload.get("template_base64") or payload.get("templateBase64") or ""
        template_hash = payload.get("template_hash") or payload.get("templateHash") or ""
        template_length = int(payload.get("template_length") or payload.get("templateLength") or 0)
        device_code = payload.get("device_code") or payload.get("deviceCode") or ""
        source_device = self._find_device(event.controller_id, device_code)
        collected_at = fields.Datetime.now()

        rec = self.sudo().search([
            ("user_id", "=", user.id),
            ("finger_index", "=", finger_index),
            ("template_version", "=", template_version),
        ], limit=1)

        if not rec:
            rec = self.sudo().create({
                "user_id": user.id,
                "finger_index": finger_index,
                "template_version": template_version,
                "template_base64": template_base64,
                "template_hash": template_hash,
                "template_length": template_length,
                "source_device_id": source_device.id if source_device else False,
                "source_device_code": device_code,
                "last_collected_at": collected_at,
                "status": "active",
                "server_version": 1,
                "note": "Created from Controller fingerprint_collected event.",
            })
            # New master captured from a real device becomes active and is pushed to other active devices.
            rec.queue_push_to_devices()
            return rec

        if rec.template_hash and template_hash and rec.template_hash != template_hash:
            # Do not overwrite an active server master silently. Keep the new device value as a pending candidate.
            rec.write({
                "pending_template_base64": template_base64,
                "pending_template_hash": template_hash,
                "pending_template_length": template_length,
                "pending_source_device_id": source_device.id if source_device else False,
                "pending_source_device_code": device_code,
                "pending_collected_at": collected_at,
                "status": "pending_review",
                "note": "Device sent a different fingerprint template. Review and approve on server before replacing master.",
            })
            self.env["entry.control.conflict"].sudo().with_context(
                force_conflict_type="fingerprint_mismatch_on_device"
            ).ingest_from_event(event)
            # Restore the server master to the device that reported a different hash.
            if source_device:
                rec.queue_push_to_devices(only_device=source_device)
            return rec

        rec.write({
            "template_base64": template_base64 or rec.template_base64,
            "template_hash": template_hash or rec.template_hash,
            "template_length": template_length or rec.template_length,
            "source_device_id": source_device.id if source_device else rec.source_device_id.id,
            "source_device_code": device_code or rec.source_device_code,
            "last_collected_at": collected_at,
            "status": "active" if rec.status in ("pending_review", "rejected") else rec.status,
        })
        return rec

    @api.model
    def handle_device_drift_event(self, event):
        payload = event.payload or {}
        pin = payload.get("pin")
        finger_index = int(payload.get("finger_index") or payload.get("fingerIndex") or 0)
        template_version = payload.get("template_version") or payload.get("templateVersion") or ""
        device_code = payload.get("device_code") or payload.get("deviceCode") or ""
        if not pin:
            return False
        rec = self.sudo().search([
            ("pin", "=", pin),
            ("finger_index", "=", finger_index),
            ("template_version", "=", template_version),
            ("status", "=", "active"),
        ], limit=1)
        if not rec:
            return False
        device = self._find_device(event.controller_id, device_code)
        if device:
            rec.queue_push_to_devices(only_device=device)
        return rec
