# No automatic res.partner role assignment

`res.partner` is Odoo's Contact/Partner model. It is used for customers, vendors, contacts, addresses, and sometimes employee private/work contacts depending on the HR/contact configuration.

This module must not assign Customer/Vendor/Manufacturer/Brand roles automatically. Attendance Gateway only mirrors `hr.employee.pin` into `entry.control.user`. If another customization requires a role on every Contact, that rule must be handled by the Contacts/Partner module or by user input, not by Attendance Gateway.
