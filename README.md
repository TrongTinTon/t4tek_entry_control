# T4TEK Attendance Gateway

Local-first Odoo module for attendance, access control and fingerprint synchronization with ZKTeco devices.

## Purpose

This module is the Odoo server-side component for the T4TEK Attendance Gateway architecture. It works with the Windows Controller application, which connects to ZKTeco devices on the local network.

## Main capabilities

- Controller self-registration and token-based authentication.
- Controller lifecycle management with Block / Unblock actions.
- Desired-State Sync for Device Users, assignments and deleted users.
- Fingerprint Master workflow:
  - Harvest fingerprint templates from a source device via Controller.
  - Upload templates to Odoo Fingerprint Master.
  - Distribute templates to multiple local ZKTeco devices using optimized `sync_fingerprint_set` jobs.
- Attendance log ingestion from Controller to Odoo.
- OWL fingerprint map widget on Device User form.

## Fingerprint widget

The Device User form includes the OWL field widget `ec_fingerprint_map`. It renders a 10-finger status map from `fingerprint_map_json` and does not expose raw `template_base64` data on the UI.

## Module identity

- Technical folder name: `t4tek_entry_control`
- Display name: `T4TEK Attendance Gateway`
- Category: `Human Resources / Attendances`
