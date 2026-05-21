from odoo import fields, models, _


class EntryControlTokenWizard(models.TransientModel):
    _name = "entry.control.token.wizard"
    _description = "Entry Control Controller Token Wizard"

    controller_id = fields.Many2one("entry.control.controller", required=True, readonly=True)
    token = fields.Text(required=True, readonly=True)
    note = fields.Text(default=lambda self: _("Copy this token now. It is shown only once and only its hash is stored."), readonly=True)
