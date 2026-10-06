from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .constants import INSURANCE_CLASSES


class InsuranceClaimDocumentTemplate(models.Model):
    """Per line-of-business preset checklist loaded onto a new claim."""

    _name = "insurance.claim.document.template"
    _description = "Insurance Claim Document Template"
    _order = "insurance_class, sequence, id"

    name = fields.Char(required=True, translate=True)
    insurance_class = fields.Selection(
        INSURANCE_CLASSES,
        string="Business Class",
        required=True,
        default="general",
        index=True,
        help="Checklist preset applied to claims of this line of business.",
    )
    description = fields.Text(translate=True)
    is_required = fields.Boolean(
        default=True,
        help="Required documents gate progression to the 'Lodged with Insurer' stage.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _unique_class_name = models.Constraint(
        "unique(insurance_class, name)",
        "This document already exists for the selected business class.",
    )

    @api.model
    def _templates_for(self, insurance_class):
        """Return active templates for a class, falling back to the generic set."""
        if not insurance_class:
            insurance_class = "general"
        domain = [("insurance_class", "=", insurance_class)]
        templates = self.search(domain)
        if not templates and insurance_class != "general":
            templates = self.search([("insurance_class", "=", "general")])
        return templates


class InsuranceClaimDocument(models.Model):
    _name = "insurance.claim.document"
    _description = "Insurance Claim Document"
    _order = "sequence, id"

    claim_id = fields.Many2one(
        "insurance.claim",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char(required=True)
    description = fields.Text(
        help="What the broker should ask the client for.",
    )
    sequence = fields.Integer(default=10)
    is_required = fields.Boolean(default=True)
    is_received = fields.Boolean(
        string="Received",
        copy=False,
    )
    received_date = fields.Date(copy=False)
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="Attached File",
        ondelete="set null",
        copy=False,
    )
    notes = fields.Text()

    @api.onchange("is_received")
    def _onchange_is_received(self):
        for rec in self:
            if rec.is_received and not rec.received_date:
                rec.received_date = fields.Date.context_today(rec)
            elif not rec.is_received:
                rec.received_date = False

    def action_mark_received(self):
        for rec in self:
            rec.write({"is_received": True, "received_date": fields.Date.context_today(rec)})
        return True

    def action_mark_outstanding(self):
        for rec in self:
            rec.write({"is_received": False, "received_date": False})
        return True

    @api.constrains("is_received", "received_date")
    def _check_received_date(self):
        for rec in self:
            if rec.is_received and not rec.received_date:
                raise ValidationError(
                    _("Document '%(name)s' is marked received but has no received date.", name=rec.name)
                )
            if not rec.is_received and rec.received_date:
                raise ValidationError(
                    _("Document '%(name)s' has a received date but is not marked received.", name=rec.name)
                )
