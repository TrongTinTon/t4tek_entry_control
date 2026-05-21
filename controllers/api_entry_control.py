import hashlib
import json
import re
from datetime import datetime, timezone

from dateutil import parser as date_parser
from odoo import fields, http
from odoo.http import Response, request


class EntryControlAPI(http.Controller):
    """HTTP API for desired-state Entry Control sync.

    Workflow:
    - /auth/token is the only bootstrap endpoint that may create/activate a Controller.
    - /hello and all operational APIs require runtime token.
    - Odoo exposes desired-state manifest sync as the main mechanism.
    - Controller pulls desired-state manifest by last_sync_version, then computes local device jobs.
    """

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------
    def _json_response(self, payload, status=200):
        return Response(json.dumps(payload, ensure_ascii=False, default=str), content_type="application/json", status=status)

    def _read_json_body(self):
        raw_data = request.httprequest.data
        if not raw_data:
            return {}
        try:
            return json.loads(raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data)
        except Exception:
            return {}

    def _get_header_token(self):
        token = (request.httprequest.headers.get("X-Controller-Token") or "").strip()
        if token:
            return token
        auth = request.httprequest.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def _normalize_controller_code(self, code):
        return (code or "").strip().upper()

    def _get_controller_code(self, data):
        # Important: do not accept controller_id/controllerId as business code.
        # Those names are ambiguous with Odoo database ids and caused duplicate Controllers.
        return self._normalize_controller_code(
            request.httprequest.headers.get("X-Controller-Code")
            or data.get("controller_code")
            or data.get("controllerCode")
            or ""
        )

    def _safe_int(self, value, default=0):
        try:
            if value in (None, False, ""):
                return default
            return int(value)
        except Exception:
            return default

    def _safe_bool(self, value, default=False):
        if value in (None, False, ""):
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "y", "on"):
            return True
        if text in ("0", "false", "no", "n", "off"):
            return False
        return default

    def _parse_datetime_utc(self, value):
        if not value:
            return fields.Datetime.now()
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if not text:
                return fields.Datetime.now()
            text = re.sub(r"(\.\d{6})\d+([+-Z])", r"\1\2", text)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                if "T" in text or "+" in text[-6:] or "-" in text[-6:]:
                    dt = date_parser.isoparse(text)
                else:
                    dt = fields.Datetime.to_datetime(text)
            except Exception:
                dt = date_parser.parse(text)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _version_from_dt(self, dt):
        if not dt:
            return 0
        if not isinstance(dt, datetime):
            dt = fields.Datetime.to_datetime(dt)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000000)

    def _dt_from_version(self, version):
        try:
            version = int(version or 0)
        except Exception:
            version = 0
        if version <= 0:
            return False
        return datetime.fromtimestamp(version / 1000000.0, timezone.utc).replace(tzinfo=None)

    def _hash_dict(self, data):
        text = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _find_controller(self, code):
        code = self._normalize_controller_code(code)
        if not code:
            return request.env["entry.control.controller"].sudo().browse()
        return request.env["entry.control.controller"].sudo().search([("controller_code", "=", code)], limit=1)

    def _auth_controller(self, data=None):
        data = data or self._read_json_body()
        code = self._get_controller_code(data)
        if not code:
            return None, self._json_response({"ok": False, "error": "controller_code is required"}, 400)
        controller = self._find_controller(code)
        if not controller:
            return None, self._json_response({"ok": False, "error": "Unknown controller_code"}, 404)
        if controller.blocked or controller.registration_status == "blocked" or not controller.approved:
            controller.sudo().write({"last_seen_at": fields.Datetime.now(), "last_error": "Blocked/unapproved controller attempted API call."})
            return None, self._json_response({"ok": False, "blocked": True, "error": "Controller is blocked or not approved"}, 403)
        token = self._get_header_token() or (data.get("access_token") or data.get("controller_token") or data.get("controllerToken") or "").strip()
        if not controller.check_token(token):
            return None, self._json_response({"ok": False, "error": "Invalid or missing controller token"}, 401)
        if "token_expires_at" in controller._fields and controller.token_expires_at and controller.token_expires_at <= fields.Datetime.now():
            return None, self._json_response({"ok": False, "error": "Controller token expired", "token_expired": True}, 401)
        controller.sudo().write({"last_seen_at": fields.Datetime.now(), "last_error": False})
        return controller, None

    def _user_hash(self, user, fingerprint_set_hash=""):
        return self._hash_dict({
            "pin": user.pin or "",
            "name": user.name or "",
            "password": user.password or "",
            "card_no": user.card_no or "",
            "privilege": user.privilege or 0,
            "group_no": user.group_no or 1,
            "timezone_no": user.timezone_no or 1,
            "is_active": bool(user.is_active),
            "is_deleted": bool(user.is_deleted),
            "fingerprint_set_hash": fingerprint_set_hash or "",
        })

    def _fingerprint_set_hash(self, user):
        fps = user.fingerprint_ids.sudo().filtered(lambda f: f.status == "active")
        items = []
        for fp in fps.sorted(lambda f: (f.finger_index or 0, f.template_version or "")):
            items.append({
                "finger_index": fp.finger_index or 0,
                "template_version": fp.template_version or "",
                "template_hash": fp.template_hash or "",
                "template_length": fp.template_length or 0,
                "status": fp.status or "",
            })
        return self._hash_dict(items)

    def _user_to_manifest(self, user, assignment_scope="controller_all_devices"):
        fp_hash = self._fingerprint_set_hash(user)
        write_version = max([
            self._version_from_dt(user.write_date),
            self._version_from_dt(max(user.fingerprint_ids.sudo().mapped("write_date") or [False])),
        ])
        return {
            "user_id": user.id,
            "server_user_id": str(user.id),
            "pin": user.pin or "",
            "name": user.name or "",
            "password": user.password or "",
            "card_no": user.card_no or "",
            "privilege": user.privilege or 0,
            "group_no": user.group_no or 1,
            "timezone_no": user.timezone_no or 1,
            "is_active": bool(user.is_active),
            "enabled": bool(user.is_active and not user.is_deleted),
            "is_deleted": bool(user.is_deleted),
            "deleted": bool(user.is_deleted),
            "assignment_scope": assignment_scope,
            "apply_to_all_devices": assignment_scope == "controller_all_devices",
            "fingerprint_set_hash": fp_hash,
            "user_hash": self._user_hash(user, fp_hash),
            "write_version": write_version,
            "write_date": fields.Datetime.to_string(user.write_date) if user.write_date else "",
        }

    def _fingerprint_to_manifest(self, fp):
        return {
            "fingerprint_id": fp.id,
            "server_fingerprint_id": str(fp.id),
            "fingerprint_uid": fp.fingerprint_uid or "",
            "pin": fp.pin or "",
            "finger_index": fp.finger_index or 0,
            "template_version": fp.template_version or "",
            "template_hash": fp.template_hash or "",
            "template_length": fp.template_length or 0,
            "status": fp.status or "active",
            "desired_state": "active" if fp.status == "active" else ("deleted" if fp.status == "deleted" else "disabled"),
            "write_version": self._version_from_dt(fp.write_date),
            "write_date": fields.Datetime.to_string(fp.write_date) if fp.write_date else "",
        }

    # ------------------------------------------------------------------
    # Public health
    # ------------------------------------------------------------------
    @http.route(["/api/entry_control/v1/health", "/api/entry_control/v1/health/"], type="http", auth="none", methods=["GET", "POST"], csrf=False)
    def health(self, **kwargs):
        db = request.httprequest.args.get("db") or request.httprequest.headers.get("X-Odoo-Database") or ""
        return self._json_response({
            "ok": True,
            "service": "t4_entry_control_odoo",
            "status": "running",
            "sync_mode": "desired_state_manifest",
            "odoo_database": db,
            "server_time": fields.Datetime.to_string(fields.Datetime.now()),
        })

    # ------------------------------------------------------------------
    # Controller lifecycle
    # ------------------------------------------------------------------
    @http.route("/api/entry_control/v1/auth/token", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_auth_token(self, **kwargs):
        try:
            data = self._read_json_body()
            code = self._get_controller_code(data)
            if not code:
                return self._json_response({"ok": False, "error": "controller_code is required"}, 400)
            payload = dict(data)
            payload["controller_code"] = code
            payload.setdefault("controller_name", data.get("controllerName") or data.get("name") or code)
            controller = request.env["entry.control.controller"].sudo().upsert_from_hello(payload, mark_hello=False)
            if controller.blocked or controller.registration_status == "blocked":
                return self._json_response({"ok": False, "blocked": True, "controller_code": controller.controller_code, "message": "Controller is blocked."}, 403)
            token = controller.issue_runtime_token()
            expires_in = 3600
            expires_at = ""
            if "token_expires_at" in controller._fields and controller.token_expires_at:
                expires_at = fields.Datetime.to_string(controller.token_expires_at)
                try:
                    expires_in = max(1, int((controller.token_expires_at - fields.Datetime.now()).total_seconds()))
                except Exception:
                    expires_in = 3600
            return self._json_response({
                "ok": True,
                "status": "success",
                "controller_code": controller.controller_code,
                "controller_id": controller.id,
                "approved": bool(controller.approved),
                "blocked": bool(controller.blocked),
                "registration_status": controller.registration_status,
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "expires_at": expires_at,
                "server_time": fields.Datetime.to_string(fields.Datetime.now()),
            })
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    @http.route(["/api/entry_control/v1/auth/refresh"], type="http", auth="public", methods=["POST"], csrf=False)
    def v1_auth_refresh(self, **kwargs):
        return self.v1_auth_token(**kwargs)

    @http.route("/api/entry_control/v1/hello", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_hello(self, **kwargs):
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error
            vals = {
                "last_hello_at": fields.Datetime.now(),
                "last_seen_at": fields.Datetime.now(),
                "app_version": data.get("app_version") or data.get("version"),
                "machine_name": data.get("machine_name") or data.get("machineName"),
                "local_ip": data.get("local_ip") or data.get("localIp"),
                "last_error": False,
            }
            controller.sudo().write({k: v for k, v in vals.items() if v is not None})
            return self._json_response({
                "ok": True,
                "status": "success",
                "controller_code": controller.controller_code,
                "controller_id": controller.id,
                "approved": bool(controller.approved),
                "blocked": bool(controller.blocked),
                "registration_status": controller.registration_status,
                "server_time": fields.Datetime.to_string(fields.Datetime.now()),
            })
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    @http.route("/api/entry_control/v1/devices/report", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_devices_report(self, **kwargs):
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error
            devices = data.get("devices") or []
            if not isinstance(devices, list):
                return self._json_response({"ok": False, "error": "devices must be a list"}, 400)
            Device = request.env["entry.control.device"].sudo()
            results = []
            for item in devices:
                if not isinstance(item, dict):
                    continue
                device = Device.upsert_from_payload(controller, item)
                if device:
                    results.append({"device_code": device.device_code, "device_id": device.id, "is_online": bool(device.is_online)})
            controller.sudo().write({"last_device_report_at": fields.Datetime.now(), "last_seen_at": fields.Datetime.now()})
            return self._json_response({"ok": True, "status": "success", "controller_code": controller.controller_code, "received": len(results), "devices": results})
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    # ------------------------------------------------------------------
    # Desired-state sync APIs
    # ------------------------------------------------------------------
    @http.route("/api/entry_control/v1/sync/manifest", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_sync_manifest(self, **kwargs):
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error
            last_version = self._safe_int(data.get("last_sync_version", data.get("lastSyncVersion", 0)), 0)
            full = self._safe_bool(data.get("full", data.get("fullSync", False)), False) or last_version <= 0
            snapshot_at = fields.Datetime.now()
            snapshot_version = self._version_from_dt(snapshot_at)
            cutoff = self._dt_from_version(last_version)

            User = request.env["entry.control.user"].sudo()
            Fingerprint = request.env["entry.control.fingerprint"].sudo()
            Assignment = request.env["entry.control.assignment"].sudo()

            explicit_pins = data.get("pins") or []
            if isinstance(explicit_pins, str):
                explicit_pins = [p.strip() for p in explicit_pins.split(",") if p.strip()]
            pins = set([str(p).strip() for p in explicit_pins if str(p).strip()])

            if not pins:
                if full:
                    pins.update(User.search([]).mapped("pin"))
                else:
                    pins.update(User.search([("write_date", ">", cutoff), ("write_date", "<=", snapshot_at)]).mapped("pin"))
                    pins.update(Fingerprint.search([("write_date", ">", cutoff), ("write_date", "<=", snapshot_at)]).mapped("pin"))
                    pins.update(Assignment.search([("write_date", ">", cutoff), ("write_date", "<=", snapshot_at)]).mapped("pin"))

            users_rs = User.search([("pin", "in", list(pins))]) if pins else User.browse()
            all_assignment_rs = Assignment.search([("pin", "in", list(pins))]) if pins else Assignment.browse()
            controller_assignment_rs = all_assignment_rs.filtered(lambda a: a.controller_id and a.controller_id.id == controller.id)
            pins_with_explicit_assignment = set(all_assignment_rs.mapped("pin"))

            users = []
            deleted_users = []
            for user in users_rs:
                scope = "explicit_devices" if user.pin in pins_with_explicit_assignment else "controller_all_devices"
                item = self._user_to_manifest(user, assignment_scope=scope)
                users.append(item)
                if user.is_deleted:
                    deleted_users.append({"pin": user.pin, "delete_version": item["write_version"], "deleted_at": fields.Datetime.to_string(user.write_date) if user.write_date else ""})

            assignments = []
            for a in controller_assignment_rs:
                assignments.append({
                    "pin": a.pin or "",
                    "device_code": a.device_code or "",
                    "device_codes": [a.device_code] if a.device_code else [],
                    "desired_state": a.desired_state or "present",
                    "assignment_id": a.id,
                    "write_version": self._version_from_dt(a.write_date),
                })

            fp_rs = Fingerprint.search([("pin", "in", list(pins))]) if pins else Fingerprint.browse()
            fp_manifest = [self._fingerprint_to_manifest(fp) for fp in fp_rs]

            vals = {"last_seen_at": fields.Datetime.now()}
            if "last_manifest_pull_at" in controller._fields:
                vals["last_manifest_pull_at"] = fields.Datetime.now()
            controller.sudo().write(vals)
            return self._json_response({
                "ok": True,
                "status": "success",
                "sync_mode": "desired_state_manifest",
                "controller_code": controller.controller_code,
                "last_sync_version": last_version,
                "sync_version": snapshot_version,
                "server_time": fields.Datetime.to_string(snapshot_at),
                "count": len(users),
                "users": users,
                "deleted_users": deleted_users,
                "assignments": assignments,
                "fingerprint_manifests": fp_manifest,
            })
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    @http.route("/api/entry_control/v1/sync/fingerprints", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_sync_fingerprints(self, **kwargs):
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error
            pins = data.get("pins") or []
            if isinstance(pins, str):
                pins = [p.strip() for p in pins.split(",") if p.strip()]
            pins = [str(p).strip() for p in pins if str(p).strip()]
            if not pins:
                return self._json_response({"ok": False, "error": "pins is required"}, 400)
            Fingerprint = request.env["entry.control.fingerprint"].sudo()
            fps = Fingerprint.search([("pin", "in", pins)])
            items = []
            for fp in fps:
                item = self._fingerprint_to_manifest(fp)
                # Only active templates carry heavy payload.
                if fp.status == "active":
                    item.update({"template_base64": fp.template_base64 or ""})
                items.append(item)
            controller.sudo().write({"last_seen_at": fields.Datetime.now()})
            return self._json_response({"ok": True, "status": "success", "count": len(items), "fingerprints": items})
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)



    @http.route("/api/entry_control/v1/sync/fingerprints/upload", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_sync_fingerprints_upload(self, **kwargs):
        """Receive harvested fingerprint templates from a Controller/source device.

        This endpoint is Luồng A in the desired-state architecture:
        source device -> Controller local ec_user_fingerprint -> Odoo fingerprint master.
        It does not create device commands. Downstream devices receive changes later through
        /sync/manifest + /sync/fingerprints + Controller local sync_fingerprint_set jobs.
        """
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error

            items = data.get("fingerprints") or data.get("templates") or []
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                return self._json_response({"ok": False, "error": "fingerprints must be a list"}, 400)

            User = request.env["entry.control.user"].sudo()
            Fingerprint = request.env["entry.control.fingerprint"].sudo()
            Device = request.env["entry.control.device"].sudo()

            uploaded = []
            pending_review = []
            failed = []
            now = fields.Datetime.now()

            for index, item in enumerate(items):
                try:
                    if not isinstance(item, dict):
                        raise ValueError("fingerprint item must be an object")
                    pin = str(item.get("pin") or "").strip()
                    if not pin:
                        raise ValueError("pin is required")
                    user = User.search([("pin", "=", pin)], limit=1)
                    if not user:
                        raise ValueError("Unknown Device User PIN %s. Create Device User on Odoo first." % pin)

                    finger_index = self._safe_int(item.get("finger_index", item.get("fingerIndex", 0)), 0)
                    template_version = str(item.get("template_version") or item.get("templateVersion") or "").strip()
                    template_base64 = item.get("template_base64") or item.get("templateBase64") or item.get("template_data") or item.get("templateData") or ""
                    template_base64 = str(template_base64 or "").strip()
                    if not template_base64:
                        raise ValueError("template_base64 is required")
                    template_hash = str(item.get("template_hash") or item.get("templateHash") or "").strip()
                    if not template_hash:
                        template_hash = self._hash_dict({"template_base64": template_base64})
                    template_length = self._safe_int(item.get("template_length", item.get("templateLength", 0)), 0)
                    source_device_code = str(item.get("source_device_code") or item.get("sourceDeviceCode") or item.get("device_code") or item.get("deviceCode") or "").strip()
                    local_id = item.get("local_id") or item.get("localId")
                    replace_master = self._safe_bool(item.get("replace_master", item.get("replaceMaster", False)), False)

                    source_device = Device.browse()
                    if source_device_code:
                        source_device = Device.search([
                            ("controller_id", "=", controller.id),
                            ("device_code", "=", source_device_code),
                        ], limit=1)

                    rec = Fingerprint.search([
                        ("user_id", "=", user.id),
                        ("finger_index", "=", finger_index),
                        ("template_version", "=", template_version),
                    ], limit=1)

                    vals_active = {
                        "template_base64": template_base64,
                        "template_hash": template_hash,
                        "template_length": template_length,
                        "source_device_id": source_device.id if source_device else False,
                        "source_device_code": source_device_code,
                        "last_collected_at": now,
                        "status": "active",
                    }

                    if not rec:
                        rec = Fingerprint.create(dict(vals_active, **{
                            "user_id": user.id,
                            "finger_index": finger_index,
                            "template_version": template_version,
                            "server_version": 1,
                            "note": "Created from Controller fingerprint upload.",
                        }))
                        uploaded.append({"index": index, "local_id": local_id, "fingerprint_id": rec.id, "pin": pin, "finger_index": finger_index, "status": "active", "created": True})
                        continue

                    current_hash = rec.template_hash or ""
                    if current_hash and current_hash != template_hash and rec.status == "active" and not replace_master:
                        rec.write({
                            "pending_template_base64": template_base64,
                            "pending_template_hash": template_hash,
                            "pending_template_length": template_length,
                            "pending_source_device_id": source_device.id if source_device else False,
                            "pending_source_device_code": source_device_code,
                            "pending_collected_at": now,
                            "status": "pending_review",
                            "note": "Controller uploaded a different fingerprint template. Review before replacing master.",
                        })
                        pending_review.append({"index": index, "local_id": local_id, "fingerprint_id": rec.id, "pin": pin, "finger_index": finger_index, "status": "pending_review"})
                        continue

                    rec.write(dict(vals_active, **{"server_version": (rec.server_version or 0) + 1, "note": "Updated from Controller fingerprint upload."}))
                    uploaded.append({"index": index, "local_id": local_id, "fingerprint_id": rec.id, "pin": pin, "finger_index": finger_index, "status": "active", "updated": True})
                except Exception as item_error:
                    failed.append({"index": index, "local_id": item.get("local_id") if isinstance(item, dict) else False, "error": str(item_error)})

            controller.sudo().write({"last_seen_at": fields.Datetime.now()})
            status = "success" if not failed and not pending_review else ("partial_error" if failed else "pending_review")
            return self._json_response({
                "ok": not bool(failed),
                "status": status,
                "received": len(items),
                "uploaded": uploaded,
                "pending_review": pending_review,
                "failed": failed,
            }, 200 if not failed else 207)
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    # ------------------------------------------------------------------
    # Deprecated command-log compatibility
    # ------------------------------------------------------------------
    @http.route("/api/entry_control/v1/commands/pull", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_commands_pull(self, **kwargs):
        data = self._read_json_body()
        controller, error = self._auth_controller(data)
        if error:
            return error
        return self._json_response({
            "ok": True,
            "status": "deprecated",
            "sync_mode": "desired_state_manifest",
            "message": "Deprecated endpoint. Use /api/entry_control/v1/sync/manifest.",
            "commands": [],
            "count": 0,
        })

    @http.route("/api/entry_control/v1/commands/ack", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_commands_ack(self, **kwargs):
        data = self._read_json_body()
        controller, error = self._auth_controller(data)
        if error:
            return error
        return self._json_response({"ok": True, "status": "ignored", "message": "Command ACK is unused in desired-state sync."})

    @http.route("/api/entry_control/v1/attendance/logs/push", type="http", auth="public", methods=["POST"], csrf=False)
    def v1_attendance_logs_push(self, **kwargs):
        try:
            data = self._read_json_body()
            controller, error = self._auth_controller(data)
            if error:
                return error
            logs = data.get("logs") or data.get("attendance_logs") or []
            if isinstance(logs, dict):
                logs = [logs]
            if not isinstance(logs, list):
                return self._json_response({"ok": False, "error": "logs must be a list"}, 400)
            Attendance = request.env["entry.control.attendance.log"].sudo()
            created = 0
            duplicate = 0
            failed = []
            ids = []
            for index, log in enumerate(logs):
                try:
                    if not isinstance(log, dict):
                        raise ValueError("log item must be an object")
                    record, is_duplicate = Attendance.ingest_direct_log(controller, log)
                    ids.append(record.id)
                    if is_duplicate:
                        duplicate += 1
                    else:
                        created += 1
                except Exception as log_error:
                    failed.append({"index": index, "error": str(log_error)})
            controller.sudo().write({"last_seen_at": fields.Datetime.now()})
            return self._json_response({
                "ok": not bool(failed),
                "status": "success" if not failed else "partial_error",
                "received": len(logs),
                "created": created,
                "duplicates": duplicate,
                "failed": failed,
                "attendance_log_ids": ids,
            }, 200 if not failed else 207)
        except Exception as e:
            return self._json_response({"ok": False, "error": str(e)}, 500)

    # ------------------------------------------------------------------
    # Legacy aliases
    # ------------------------------------------------------------------
    @http.route(["/api/entry_control/controller/health", "/api/entry_control/controller/heartbeat"], type="http", auth="public", methods=["POST"], csrf=False)
    def legacy_heartbeat(self, **kwargs):
        data = self._read_json_body()
        controller, error = self._auth_controller(data)
        if error:
            return error
        controller.sudo().write({"last_seen_at": fields.Datetime.now(), "last_error": False})
        return self._json_response({"ok": True, "status": "success", "controller_code": controller.controller_code})

    @http.route("/api/entry_control/controller/hello", type="http", auth="public", methods=["POST"], csrf=False)
    def legacy_controller_hello(self, **kwargs):
        return self.v1_hello(**kwargs)

    @http.route("/api/entry_control/controller/status", type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def legacy_status(self, **kwargs):
        data = self._read_json_body() if request.httprequest.method == "POST" else {}
        code = self._get_controller_code(data) or kwargs.get("controller_code") or ""
        controller = self._find_controller(str(code).strip())
        if not controller:
            return self._json_response({"ok": False, "status": "unknown", "approved": False}, 404)
        return self._json_response({"ok": True, "status": controller.registration_status, "approved": bool(controller.approved), "blocked": bool(controller.blocked), "controller_code": controller.controller_code})
