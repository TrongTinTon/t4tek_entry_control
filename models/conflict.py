from odoo import api, fields, models


class EntryControlConflict(models.Model):
    _name = "entry.control.conflict"
    _description = "Entry Control Sync Conflict"
    _order = "create_date desc, id desc"

    controller_id = fields.Many2one("entry.control.controller", ondelete="set null", index=True)
    device_id = fields.Many2one("entry.control.device", ondelete="set null", index=True)
    device_code = fields.Char(index=True)
    conflict_type = fields.Selection([
        ("unknown_user_on_device", "Unknown User On Device"),
        ("user_missing_on_device", "User Missing On Device"),
        ("user_data_mismatch_on_device", "User Data Mismatch On Device"),
        ("fingerprint_mismatch", "Fingerprint Mismatch"),
        ("fingerprint_missing_on_device", "Fingerprint Missing On Device"),
        ("fingerprint_mismatch_on_device", "Fingerprint Mismatch On Device"),
        ("server_version_conflict", "Server Version Conflict"),
        ("device_write_failed", "Device Write Failed"),
    ], required=True, index=True)
    entity_type = fields.Char(index=True)
    entity_key = fields.Char(index=True)
    server_value = fields.Json(default=dict)
    local_value = fields.Json(default=dict)
    device_value = fields.Json(default=dict)
    status = fields.Selection([
        ("open", "Open"),
        ("reviewing", "Reviewing"),
        ("ignored", "Ignored"),
        ("resolved", "Resolved"),
    ], default="open", required=True, index=True)
    resolution = fields.Text()
    resolved_at = fields.Datetime()

    @api.model
    def ingest_from_event(self, event):
        payload = event.payload or {}
        conflict_type = self.env.context.get("force_conflict_type") or (event.event_type if event.event_type != "sync_conflict_created" else payload.get("conflict_type"))
        conflict_type = conflict_type or "device_write_failed"
        device_code = payload.get("device_code")
        device = self.env["entry.control.device"].sudo().search([
            ("controller_id", "=", event.controller_id.id),
            ("device_code", "=", device_code),
        ], limit=1) if device_code else self.env["entry.control.device"].browse()
        entity_key = payload.get("entity_key") or payload.get("pin") or str(event.aggregate_id or "")
        if payload.get("finger_index") is not None or payload.get("fingerIndex") is not None:
            idx = payload.get("finger_index") if payload.get("finger_index") is not None else payload.get("fingerIndex")
            entity_key = "%s|finger:%s|%s" % (payload.get("pin") or entity_key, idx, payload.get("template_version") or payload.get("templateVersion") or "")
        existing = self.sudo().search([
            ("controller_id", "=", event.controller_id.id),
            ("conflict_type", "=", conflict_type),
            ("device_code", "=", device_code),
            ("entity_key", "=", entity_key),
            ("status", "in", ["open", "reviewing"]),
        ], limit=1)
        vals = {
            "controller_id": event.controller_id.id,
            "device_id": device.id if device else False,
            "device_code": device_code,
            "conflict_type": conflict_type,
            "entity_type": payload.get("entity_type") or ("fingerprint" if (payload.get("finger_index") is not None or payload.get("fingerIndex") is not None or "fingerprint" in conflict_type) else "user"),
            "entity_key": entity_key,
            "server_value": payload.get("server_value") or {},
            "local_value": payload.get("local_value") or {},
            "device_value": payload.get("device_value") or payload,
        }
        if existing:
            existing.write(vals)
            return existing
        return self.sudo().create(vals)

    def action_mark_resolved(self):
        self.write({"status": "resolved", "resolved_at": fields.Datetime.now()})
        return True

    def action_ignore(self):
        self.write({"status": "ignored", "resolved_at": fields.Datetime.now()})
        return True
