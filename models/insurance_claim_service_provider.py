from odoo import _, fields, models

from .constants import PROVIDER_TYPES


class InsuranceClaimServiceProvider(models.Model):
    _name = "insurance.claim.service.provider"
    _description = "Insurance Claim Service Provider"
    _order = "appointment_date desc, id desc"

    claim_id = fields.Many2one(
        "insurance.claim",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Service Provider",
        required=True,
        ondelete="restrict",
    )
    provider_type = fields.Selection(
        PROVIDER_TYPES,
        string="Provider Type",
        required=True,
        default="assessor",
        index=True,
    )
    appointment_date = fields.Date(
        default=lambda self: fields.Date.context_today(self),
    )
    report_received_date = fields.Date(copy=False)
    instructions = fields.Text()
    notes = fields.Text()
    active = fields.Boolean(default=True)
