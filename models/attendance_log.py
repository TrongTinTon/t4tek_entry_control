from datetime import datetime, timezone

from dateutil import parser as date_parser

from odoo import api, fields, models


class EntryControlAttendanceLog(models.Model):
    _name = "entry.control.attendance.log"
    _description = "Entry Control Attendance Log"
    _order = "check_time desc, id desc"

    controller_id = fields.Many2one("entry.control.controller", ondelete="set null", index=True)
    controller_code = fields.Char(related="controller_id.controller_code", store=True, index=True)
    device_id = fields.Many2one("entry.control.device", ondelete="set null", index=True)
    device_code = fields.Char(index=True)
    user_id = fields.Many2one("entry.control.user", ondelete="set null", index=True)
    pin = fields.Char(required=True, index=True)
    check_time = fields.Datetime(required=True, index=True)
    check_type = fields.Char()
    verify_type = fields.Char()
    work_code = fields.Char()
    raw_data = fields.Json(default=dict)
    event_hash = fields.Char(required=True, index=True, copy=False)
    sync_status = fields.Selection([
        ("received", "Received"),
        ("processed", "Processed"),
        ("duplicate", "Duplicate"),
        ("failed", "Failed"),
    ], default="received", required=True, index=True)

    _sql_constraints = [
        ("event_hash_unique", "unique(event_hash)", "Attendance event hash must be unique."),
    ]

    @api.model
    def _parse_controller_datetime(self, value):
        """Accept Controller datetime values in both Odoo and ISO-8601 forms.

        Controller may send local ISO values such as
        ``2026-05-19T21:43:07+07:00``. Odoo Datetime fields store naive UTC
        values, so timezone-aware values must be converted before create().
        """
        if not value:
            return fields.Datetime.now()
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if not text:
                return fields.Datetime.now()
            try:
                if "T" in text or text.endswith("Z") or "+" in text[-6:] or "-" in text[-6:]:
                    dt = date_parser.isoparse(text.replace("Z", "+00:00"))
                else:
                    dt = fields.Datetime.to_datetime(text)
            except Exception:
                # Last fallback: let dateutil try common formats.
                dt = date_parser.parse(text)
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @api.model
    def ingest_from_event(self, event):
        payload = event.payload or {}
        # Controller may wrap attendance under payload.log or send flat payload.
        log = payload.get("log") or payload
        event_hash = log.get("event_hash") or payload.get("event_hash")
        if not event_hash:
            event_hash = "%s|%s|%s|%s|%s" % (
                event.controller_code,
                log.get("device_code") or "",
                log.get("pin") or "",
                log.get("check_time") or "",
                log.get("verify_type") or "",
            )
        existing = self.sudo().search([("event_hash", "=", event_hash)], limit=1)
        if existing:
            return existing
        device_code = log.get("device_code") or payload.get("device_code")
        device = self.env["entry.control.device"].sudo().search([
            ("controller_id", "=", event.controller_id.id),
            ("device_code", "=", device_code),
        ], limit=1) if device_code else self.env["entry.control.device"].browse()
        user = self.env["entry.control.user"].sudo().search([("pin", "=", log.get("pin"))], limit=1)
        return self.sudo().create({
            "controller_id": event.controller_id.id,
            "device_id": device.id if device else False,
            "device_code": device_code,
            "user_id": user.id if user else False,
            "pin": log.get("pin") or "",
            "check_time": self._parse_controller_datetime(log.get("check_time") or log.get("checkTime") or payload.get("check_time") or payload.get("checkTime")),
            "check_type": log.get("check_type"),
            "verify_type": str(log.get("verify_type") or ""),
            "work_code": str(log.get("work_code") or ""),
            "raw_data": log,
            "event_hash": event_hash,
            "sync_status": "received",
        })

    @api.model
    def ingest_direct_log(self, controller, log):
        """Create/update Attendance Log directly from Controller API.

        This replaces the old Incoming Events/outbox flow. Controller sends
        pulled attendance batches directly to /api/entry_control/v1/attendance/logs/push.
        Idempotency is by event_hash.
        """
        log = dict(log or {})
        event_hash = log.get("event_hash") or log.get("eventHash")
        if not event_hash:
            event_hash = "%s|%s|%s|%s|%s" % (
                controller.controller_code,
                log.get("device_code") or log.get("deviceCode") or "",
                log.get("pin") or "",
                log.get("check_time") or log.get("checkTime") or "",
                log.get("verify_type") or log.get("verifyType") or "",
            )
        existing = self.sudo().search([("event_hash", "=", event_hash)], limit=1)
        if existing:
            return existing, True

        device_code = log.get("device_code") or log.get("deviceCode")
        device = self.env["entry.control.device"].sudo().search([
            ("controller_id", "=", controller.id),
            ("device_code", "=", device_code),
        ], limit=1) if device_code else self.env["entry.control.device"].browse()
        user = self.env["entry.control.user"].sudo().search([("pin", "=", log.get("pin"))], limit=1)
        raw = log.get("raw_data") or log.get("rawData") or log
        record = self.sudo().create({
            "controller_id": controller.id,
            "device_id": device.id if device else False,
            "device_code": device_code,
            "user_id": user.id if user else False,
            "pin": log.get("pin") or "",
            "check_time": self._parse_controller_datetime(log.get("check_time") or log.get("checkTime")),
            "check_type": str(log.get("check_type") or log.get("checkType") or ""),
            "verify_type": str(log.get("verify_type") or log.get("verifyType") or ""),
            "work_code": str(log.get("work_code") or log.get("workCode") or ""),
            "raw_data": raw if isinstance(raw, dict) else {"raw": raw},
            "event_hash": event_hash,
            "sync_status": "received",
        })
        return record, False

