# Odoo Attendance / hr_attendance Integration Fix

## Scope
This source is fixed directly from `t4tek_entry_control.zip`.

## Main changes

1. Attendance Logs now integrate with Odoo Attendances (`hr.attendance`).
   - `entry.control.attendance.log` creates or updates `hr.attendance` records.
   - Check-in creates an open HR Attendance.
   - Check-out closes the latest open HR Attendance for the employee.
   - If an employee/PIN cannot be resolved, or check-out has no open attendance, the log is marked `failed` and shows an error message.

2. Timezone handling is corrected for Controller timestamps.
   - Example Controller timestamp: `2026-05-22 03:55:31+07`.
   - `check_time` stores device-local wall-clock time: `2026-05-22 03:55:31`.
   - `check_time_utc` stores normalized UTC value for Odoo/hr.attendance audit.
   - `check_time_raw` and `check_time_timezone` preserve the original payload.

3. Server-side sync visibility is improved.
   - Attendance Log stores Controller, Device, Employee, HR Attendance link, sync status, sync message and error message.
   - Attendance Log list view uses red decoration for failed rows and green decoration for synced rows.
   - `/api/entry_control/v1/attendance/logs/push` now returns per-row results to Controller.

4. Verification method is captured.
   - Fingerprint/Card/PIN/Password/Face/Palm/QR/Mixed/Unknown are stored on each log.
   - HR Attendance has Entry Control in/out method fields.

5. Employee → Device User is automatic.
   - Creating an Employee with PIN automatically creates a matching Device User.
   - Updating Employee PIN/name/active updates the linked Device User.
   - Manual `Generate from Employees` wizard/view is removed from the loaded module.

6. Sync Conflicts UI is removed from the loaded menu/data.
   - The legacy model is kept internally for compatibility with older code paths, but the menu/view is no longer loaded.

7. Controller Block is kept and enforced.
   - Blocked/unapproved Controllers are rejected by API authentication.
