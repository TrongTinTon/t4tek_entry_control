# -*- coding: utf-8 -*-

from odoo import api, fields, models


class EntryControlUserFingerprintMap(models.Model):
    _inherit = "entry.control.user"

    fingerprint_map_json = fields.Json(
        string="Fingerprint Map",
        compute="_compute_fingerprint_map_json",
        readonly=True,
    )

    @api.depends(
        "pin",
        "fingerprint_ids.finger_index",
        "fingerprint_ids.template_version",
        "fingerprint_ids.template_hash",
        "fingerprint_ids.pending_template_hash",
        "fingerprint_ids.status",
        "fingerprint_ids.source_device_code",
        "fingerprint_ids.last_collected_at",
        "fingerprint_ids.last_pushed_at",
        "fingerprint_ids.last_deleted_at",
    )
    def _compute_fingerprint_map_json(self):
        finger_names = {
            0: "Út trái",
            1: "Áp út trái",
            2: "Giữa trái",
            3: "Trỏ trái",
            4: "Cái trái",
            5: "Cái phải",
            6: "Trỏ phải",
            7: "Giữa phải",
            8: "Áp út phải",
            9: "Út phải",
        }
        status_priority = {
            "active": 0,
            "pending_review": 1,
            "disabled": 2,
            "deleted": 3,
            "rejected": 4,
        }

        def _safe_int(value, default=0):
            try:
                return int(value or default)
            except Exception:
                return default

        for rec in self:
            by_index = {}
            active_count = 0
            pending_count = 0

            # Pick one representative record per finger index for the map.
            # Active master has highest priority. Pending candidates are still shown.
            for fp in rec.fingerprint_ids.sorted(
                key=lambda item: (
                    int(item.finger_index or 0),
                    status_priority.get(item.status or "", 99),
                    -_safe_int(item.server_version),
                    -_safe_int(item.id),
                )
            ):
                index = int(fp.finger_index or 0)
                if index < 0 or index > 9 or index in by_index:
                    continue

                has_template = bool(fp.template_hash and fp.status == "active")
                has_pending = bool(fp.pending_template_hash)
                if has_template:
                    active_count += 1
                if has_pending or fp.status == "pending_review":
                    pending_count += 1

                by_index[index] = {
                    "index": index,
                    "name": finger_names.get(index, "Finger %s" % index),
                    "has_template": has_template,
                    "has_pending": has_pending,
                    "status": fp.status or "empty",
                    "template_version": fp.template_version or "",
                    "template_hash": fp.template_hash or "",
                    "pending_template_hash": fp.pending_template_hash or "",
                    "source_device_code": fp.source_device_code or "",
                    "last_collected_at": fields.Datetime.to_string(fp.last_collected_at) if fp.last_collected_at else "",
                    "last_pushed_at": fields.Datetime.to_string(fp.last_pushed_at) if fp.last_pushed_at else "",
                    "last_deleted_at": fields.Datetime.to_string(fp.last_deleted_at) if fp.last_deleted_at else "",
                }

            fingers = []
            for index in range(10):
                fingers.append(by_index.get(index) or {
                    "index": index,
                    "name": finger_names.get(index, "Finger %s" % index),
                    "has_template": False,
                    "has_pending": False,
                    "status": "empty",
                    "template_version": "",
                    "template_hash": "",
                    "pending_template_hash": "",
                    "source_device_code": "",
                    "last_collected_at": "",
                    "last_pushed_at": "",
                    "last_deleted_at": "",
                })

            rec.fingerprint_map_json = {
                "pin": rec.pin or "",
                "count": active_count,
                "pending_count": pending_count,
                "fingers": fingers,
            }
