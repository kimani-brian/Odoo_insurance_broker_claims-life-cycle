from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .constants import COVER_STATES


class InsurancePolicy(models.Model):
    """Claims and loss-ratio analytics layered onto the finance policy book.

    ``insurance.policy`` is owned by ``insurance_broker_finance``. This module
    only adds the claims lens: how many claims a policy has carried, what has
    been incurred against it and what loss ratio that implies. No policy data
    is duplicated.
    """

    _inherit = "insurance.policy"

    claim_ids = fields.One2many(
        "insurance.claim",
        "policy_id",
        string="Claim History",
    )
    claim_count = fields.Integer(
        string="Claims",
        compute="_compute_claim_analytics",
        store=True,
    )
    open_claim_count = fields.Integer(
        string="Open Claims",
        compute="_compute_claim_analytics",
        store=True,
        help="Claims not yet in a closed stage.",
    )
    earned_premium = fields.Monetary(
        string="Earned Premium",
        compute="_compute_claim_analytics",
        store=True,
        currency_field="currency_id",
        help="Gross premium pro-rated by the share of the policy term already "
        "elapsed. The loss ratio divides by this, not by the full-period premium.",
    )
    claims_incurred_total = fields.Monetary(
        string="Total Incurred Claims",
        compute="_compute_claim_analytics",
        store=True,
        currency_field="currency_id",
    )
    loss_ratio = fields.Float(
        string="Loss Ratio (%)",
        compute="_compute_claim_analytics",
        store=True,
        digits=(5, 2),
        help="Total incurred claims divided by earned premium, as a percentage.",
    )
    loss_ratio_band = fields.Selection(
        [
            ("low", "Low / Profitable"),
            ("moderate", "Moderate / Neutral"),
            ("adverse", "Adverse / Loss Making"),
        ],
        string="Loss Ratio Band",
        compute="_compute_loss_ratio_band",
    )

    @api.depends(
        "claim_ids.incurred_amount",
        "claim_ids.stage_id",
        "claim_ids.stage_id.is_closed",
        "gross_premium",
        "start_date",
        "end_date",
    )
    def _compute_claim_analytics(self):
        today = fields.Date.context_today(self)
        for rec in self:
            claims = rec.claim_ids
            rec.claim_count = len(claims)
            rec.open_claim_count = sum(1 for c in claims if not c.stage_id.is_closed)
            rec.claims_incurred_total = sum(claims.mapped("incurred_amount"))
            rec.earned_premium = rec._compute_earned_premium(today)
            if rec.earned_premium > 0.0:
                rec.loss_ratio = rec.claims_incurred_total / rec.earned_premium * 100.0
            else:
                rec.loss_ratio = 0.0

    def _compute_earned_premium(self, today):
        """Pro-rate gross premium by the elapsed share of the policy term.

        Dividing by the full-period premium overstates the ratio early in the
        term: a policy one month into a twelve month term has earned roughly 8%
        of its premium, so a modest claim already reads as severe.
        """
        self.ensure_one()
        if not self.gross_premium or not self.start_date or not self.end_date:
            return 0.0
        if self.end_date <= self.start_date:
            return self.gross_premium if today >= self.end_date else 0.0
        if today <= self.start_date:
            return 0.0
        if today >= self.end_date:
            return self.gross_premium
        total_days = (self.end_date - self.start_date).days
        elapsed_days = (today - self.start_date).days
        return self.gross_premium * (elapsed_days / total_days)

    @api.depends("loss_ratio")
    def _compute_loss_ratio_band(self):
        for rec in self:
            if rec.loss_ratio >= 70.0:
                rec.loss_ratio_band = "adverse"
            elif rec.loss_ratio >= 40.0:
                rec.loss_ratio_band = "moderate"
            else:
                rec.loss_ratio_band = "low"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_claims(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Claims"),
            "res_model": "insurance.claim",
            "view_mode": "kanban,list,form",
            "domain": [("policy_id", "=", self.id)],
            "context": {"default_policy_id": self.id},
        }

    def action_new_claim(self):
        """Start a claim straight from the policy, as a broker would."""
        self.ensure_one()
        if self.state not in COVER_STATES:
            raise UserError(
                _(
                    "Policy %(policy)s is %(state)s. A claim can only be notified "
                    "against a policy that is bound or invoiced.",
                    policy=self.name,
                    state=dict(self._fields["state"].selection).get(self.state, self.state),
                )
            )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "insurance_broker_claims.action_insurance_claim"
        )
        action = action.copy()
        action["domain"] = [("policy_id", "=", self.id)]
        action["context"] = {
            "default_policy_id": self.id,
            "default_client_id": self.client_id.id,
            "default_underwriter_id": self.underwriter_id.id,
            "default_company_id": self.company_id.id,
        }
        return action

    # ------------------------------------------------------------------
    # Extension points implemented for insurance_broker_finance
    #
    # These are the two neutral hooks the finance module calls before deleting
    # or cancelling a policy. Overriding them is the whole integration surface:
    # the finance module owns its own workflow and knows nothing about claims,
    # and this module never wraps unlink() or action_cancel(). Removing the
    # claims addon therefore leaves finance's no-op defaults in place with no
    # dangling references.
    # ------------------------------------------------------------------
    def _check_unlink_dependents(self):
        for rec in self:
            if rec.claim_ids:
                return _(
                    "Policy %(policy)s is referenced by %(count)d claim(s). "
                    "Close or delete the claims first.",
                    policy=rec.name,
                    count=len(rec.claim_ids),
                )
        return False

    def _check_cancel_dependents(self):
        for rec in self:
            if rec.open_claim_count:
                return _(
                    "Policy %(policy)s has %(count)d open claim(s). Settle or "
                    "reopen-proof them before cancelling the policy.",
                    policy=rec.name,
                    count=rec.open_claim_count,
                )
        return False
