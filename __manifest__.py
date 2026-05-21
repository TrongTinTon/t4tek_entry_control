{
    "name": 'T4TEK Attendance Gateway',
    "summary": 'Local-first attendance, access control and fingerprint synchronization for ZKTeco devices.',
    "description": """T4TEK Attendance Gateway
========================

T4TEK Attendance Gateway connects Odoo with local Windows Controllers and ZKTeco attendance/access-control devices using a local-first architecture.

Main capabilities:
- Controller self-registration through token-based authentication.
- Controller lifecycle management with Block / Unblock control from Odoo.
- Desired-State Sync for Device Users, device assignments and deleted users.
- Fingerprint Master workflow:
  * Harvest fingerprint templates from a source device through the Controller.
  * Upload harvested templates to Odoo Fingerprint Master.
  * Distribute fingerprint templates from Odoo to multiple local devices using optimized sync_fingerprint_set jobs.
- Attendance log ingestion from local Controllers into Odoo.
- OWL fingerprint map widget on Device User forms to visualize 10-finger enrollment status without exposing raw template data.

Designed workflow:
1. Controller requests /api/entry_control/v1/auth/token.
2. Controller calls /api/entry_control/v1/hello with token for heartbeat/check-in.
3. Controller uploads harvested fingerprints to /api/entry_control/v1/sync/fingerprints/upload.
4. Controller pulls /api/entry_control/v1/sync/manifest for desired-state deltas.
5. Controller pulls /api/entry_control/v1/sync/fingerprints only when fingerprint hashes changed.
6. Controller computes local device jobs and synchronizes users/fingerprints to ZKTeco devices.
""",
    "version": '19.0.16.0',
    "category": 'Human Resources/Attendances',
    "author": 'T4TEK',
    "maintainer": 'T4TEK',
    "website": 'https://t4tek.local',
    "license": 'LGPL-3',
    "sequence": 10,
    "depends": [
        'base',
        'hr',
        'web',
    ],
    "data": [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/controller_views.xml',
        'views/device_views.xml',
        'views/employee_generate_wizard_views.xml',
        'views/user_views.xml',
        'views/fingerprint_views.xml',
        'views/assignment_views.xml',
        'views/attendance_views.xml',
        'views/conflict_views.xml',
        'views/menu_views.xml',
    ],
    "assets": {
        'web.assets_backend': [
            't4tek_entry_control/static/src/js/fingerprint_map_field.js',
            't4tek_entry_control/static/src/xml/fingerprint_map_field.xml',
            't4tek_entry_control/static/src/scss/fingerprint_map_field.scss',
        ],
    },
    "images": [
        'static/description/icon.png',
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
