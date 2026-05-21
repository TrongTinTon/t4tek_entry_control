{
    "name": "T4 Entry Control Local-First",
    "summary": "Server-side module for Local-First Attendance Controller / ZKTeco integration",
    "description": """
T4 Entry Control Local-First
============================

Odoo/server-side module for the Local-First Controller architecture.

Current workflow:
- Controller authenticates by /api/entry_control/v1/auth/token.
- /hello is token-protected and only updates heartbeat.
- Odoo exposes desired-state sync APIs as the operational workflow.
- Controller pulls /api/entry_control/v1/sync/manifest using last_sync_version.
- Controller pulls heavy fingerprint payload only through /api/entry_control/v1/sync/fingerprints when fingerprint hashes changed.
- Controller computes local delta jobs by device/user/fingerprint state.
- Attendance logs are pushed directly to Odoo.
""",
    "version": "19.0.14.0",
    "category": "Human Resources/Attendances",
    "author": "T4TEK",
    "website": "https://t4tek.local",
    "license": "LGPL-3",
    "depends": ["base", "hr"],
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "views/controller_views.xml",
        "views/device_views.xml",
        "views/employee_generate_wizard_views.xml",
        "views/user_views.xml",
        "views/fingerprint_views.xml",
        "views/assignment_views.xml",
        "views/attendance_views.xml",
        "views/conflict_views.xml",
        "views/menu_views.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
