from odoo import api, fields, models


def _short_value(value, left=12, right=8):
    value = value or ""
    if len(value) <= left + right + 3:
        return value
    return "%s...%s" % (value[:left], value[-right:])


class EntryControlEvent(models.Model):
    _name = "entry.control.event"
    _description = "Entry Control Incoming Event"
    _order = "received_at desc, id desc"

    event_id = fields.Char(required=True, index=True, copy=False)
    controller_id = fields.Many2one("entry.control.controller", required=True, ondelete="cascade", index=True)
    controller_code = fields.Char(related="controller_id.controller_code", store=True, index=True)
    event_type = fields.Selection([
        ("device_inventory_changed", "Device Inventory Changed"),
        ("device_status_changed", "Device Status Changed"),
        ("user_changed", "User Changed"),
        ("fingerprint_changed", "Fingerprint Changed"),
        ("attendance_log_created", "Attendance Log Created"),
        ("user_sync_result", "User Sync Result"),
        ("user_missing_on_device", "User Missing On Device"),
        ("user_data_mismatch_on_device", "User Data Mismatch On Device"),
        ("unknown_user_on_device", "Unknown User On Device"),
        ("sync_conflict_created", "Sync Conflict Created"),
        ("fingerprint_collected", "Fingerprint Collected"),
        ("fingerprint_missing_on_device", "Fingerprint Missing On Device"),
        ("fingerprint_mismatch_on_device", "Fingerprint Mismatch On Device"),
        ("fingerprint_push_result", "Fingerprint Push Result"),
        ("fingerprint_delete_result", "Fingerprint Delete Result"),
    ], required=True, index=True)
    aggregate_type = fields.Char(index=True)
    aggregate_id = fields.Char(index=True)
    aggregate_id_short = fields.Char(string="Aggregate", compute="_compute_display_short")
    payload = fields.Json(required=True, default=dict)
    status = fields.Selection([
        ("received", "Received"),
        ("processed", "Processed"),
        ("ignored", "Ignored"),
        ("failed", "Failed"),
    ], default="received", required=True, index=True)
    retry_count = fields.Integer(default=0)
    last_error = fields.Text()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    processed_at = fields.Datetime()

    @api.depends("aggregate_id")
    def _compute_display_short(self):
        for rec in self:
            rec.aggregate_id_short = _short_value(rec.aggregate_id)

    _sql_constraints = [
        ("event_id_unique", "unique(event_id)", "Event ID must be unique."),
    ]

    @api.model
    def ingest_event(self, controller, event):
        event_id = event.get("event_id") or event.get("id")
        if not event_id:
            return None, "missing_event_id"
        existing = self.sudo().search([("event_id", "=", event_id)], limit=1)
        if existing:
            # If the same event is resent after a previous processing failure,
            # retry processing instead of leaving it failed forever. This is
            # useful for attendance events that failed because of datetime format
            # issues before this module version.
            if existing.status == "failed":
                existing.write({
                    "payload": event.get("payload") or event,
                    "aggregate_type": event.get("aggregate_type") or existing.aggregate_type,
                    "aggregate_id": str(event.get("aggregate_id") or existing.aggregate_id or ""),
                    "status": "received",
                    "last_error": False,
                })
                existing._process_known_event()
                return existing, "reprocessed"
            return existing, "duplicate"
        vals = {
            "event_id": event_id,
            "controller_id": controller.id,
            "event_type": event.get("event_type"),
            "aggregate_type": event.get("aggregate_type"),
            "aggregate_id": str(event.get("aggregate_id") or ""),
            "payload": event.get("payload") or event,
            "status": "received",
        }
        rec = self.sudo().create(vals)
        rec._process_known_event()
        return rec, "accepted"

    def _process_known_event(self):
        for rec in self:
            try:
                payload = rec.payload or {}
                if rec.event_type == "attendance_log_created":
                    self.env["entry.control.attendance.log"].sudo().ingest_from_event(rec)
                elif rec.event_type in ("user_missing_on_device", "user_data_mismatch_on_device", "unknown_user_on_device", "sync_conflict_created", "fingerprint_missing_on_device", "fingerprint_mismatch_on_device"):
                    self.env["entry.control.conflict"].sudo().ingest_from_event(rec)
                    if rec.event_type in ("fingerprint_missing_on_device", "fingerprint_mismatch_on_device"):
                        self.env["entry.control.fingerprint"].sudo().handle_device_drift_event(rec)
                elif rec.event_type == "fingerprint_collected":
                    self.env["entry.control.fingerprint"].sudo().ingest_collected_from_event(rec)
                elif rec.event_type in ("fingerprint_push_result", "fingerprint_delete_result"):
                    self.env["entry.control.fingerprint"].sudo().handle_device_drift_event(rec)
                elif rec.event_type in ("device_inventory_changed", "device_status_changed"):
                    self._process_device_event(rec, payload)
                rec.write({"status": "processed", "processed_at": fields.Datetime.now(), "last_error": False})
            except Exception as exc:
                rec.write({"status": "failed", "retry_count": rec.retry_count + 1, "last_error": str(exc)})


    def action_reprocess(self):
        for rec in self:
            rec.write({"status": "received", "last_error": False, "processed_at": False})
            rec._process_known_event()
        return True

    def _process_device_event(self, rec, payload):
        devices = payload.get("devices") if isinstance(payload, dict) else []
        if not devices and isinstance(payload, dict) and payload.get("device_code"):
            devices = [payload]
        for dev_payload in devices or []:
            self.env["entry.control.device"].sudo().upsert_from_payload(rec.controller_id, dev_payload)
