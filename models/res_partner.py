from odoo import _, api, fields, models


class ResPartner(models.Model):
    """Client-level claims experience for renewal negotiation.

    Every field here is a non-stored compute: nothing is written onto
    ``res_partner``, so uninstalling this module leaves the core table
    untouched and no recompute is triggered on partner records.
    """

    _inherit = "res.partner"

    insurance_claim_policy_ids = fields.One2many(
        "insurance.policy",
        "client_id",
        string="Insured Policies",
        help="Policies from the finance module's policy book where this partner "
        "is the insured client.",
    )
    insurance_claim_ids = fields.One2many(
        "insurance.claim",
        "client_id",
        string="Claims",
    )
    insurance_claim_count = fields.Integer(compute="_compute_claims_experience")
    insurance_claims_currency_id = fields.Many2one(
        "res.currency",
        string="Claims Reporting Currency",
        default=lambda self: self.env.company.currency_id,
        # Deliberately not required: a NOT NULL column on res_partner would force
        # a value on every partner in the database, including the ones that have
        # no insurance cover at all.
        required=False,
        help="Reporting currency for the claims experience figures below. Policies "
        "held in other currencies are summed at face value, so keep this aligned "
        "with your reporting currency at renewal time.",
    )
    insurance_earned_premium_total = fields.Monetary(
        string="Earned Premium",
        compute="_compute_claims_experience",
        currency_field="insurance_claims_currency_id",
        help="Sum of earned premium across this client's in-force policies.",
    )
    insurance_claims_incurred_total = fields.Monetary(
        string="Total Incurred Claims",
        compute="_compute_claims_experience",
        currency_field="insurance_claims_currency_id",
    )
    insurance_loss_ratio = fields.Float(
        string="Loss Ratio (%)",
        compute="_compute_claims_experience",
        digits=(5, 2),
        help="Total incurred claims divided by earned premium, as a percentage. "
        "Use this at renewal to justify a premium discount or argue against an "
        "excess increase.",
    )
    insurance_loss_ratio_band = fields.Selection(
        [
            ("low", "Low / Profitable"),
            ("moderate", "Moderate / Neutral"),
            ("adverse", "Adverse / Loss Making"),
        ],
        string="Claims Experience",
        compute="_compute_claims_experience",
    )

    @api.depends(
        "insurance_claim_policy_ids.earned_premium",
        "insurance_claim_policy_ids.claims_incurred_total",
        "insurance_claim_ids.incurred_amount",
    )
    def _compute_claims_experience(self):
        for rec in self:
            earned = sum(rec.insurance_claim_policy_ids.mapped("earned_premium"))
            # Incurred is summed from the policies, then topped up with any claim
            # whose policy link was cleared (policy deleted) so the figure never
            # silently drops.
            incurred = sum(rec.insurance_claim_policy_ids.mapped("claims_incurred_total"))
            linked = rec.insurance_claim_ids.filtered("policy_id")
            orphaned = rec.insurance_claim_ids - linked
            incurred += sum(orphaned.mapped("incurred_amount"))
            rec.insurance_claim_count = len(rec.insurance_claim_ids)
            rec.insurance_earned_premium_total = earned
            rec.insurance_claims_incurred_total = incurred
            if earned > 0.0:
                ratio = incurred / earned * 100.0
            else:
                ratio = 0.0
            rec.insurance_loss_ratio = ratio
            if ratio >= 70.0:
                rec.insurance_loss_ratio_band = "adverse"
            elif ratio >= 40.0:
                rec.insurance_loss_ratio_band = "moderate"
            else:
                rec.insurance_loss_ratio_band = "low"

    def action_view_insurance_claims(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Claims"),
            "res_model": "insurance.claim",
            "view_mode": "list,form",
            "domain": [("client_id", "=", self.id)],
            "context": {"default_client_id": self.id},
        }

    def action_view_insurance_policies(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Insured Policies"),
            "res_model": "insurance.policy",
            "view_mode": "list,form",
            "domain": [("client_id", "=", self.id)],
            "context": {"default_client_id": self.id},
        }
