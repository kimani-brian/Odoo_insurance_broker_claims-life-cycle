from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class ClaimsTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.stage_model = cls.env["insurance.claim.stage"]
        cls.policy_model = cls.env["insurance.policy"]
        cls.claim_model = cls.env["insurance.claim"]

        cls.stage_fnol = cls.env.ref("insurance_broker_claims.stage_fnol")
        cls.stage_documents = cls.env.ref("insurance_broker_claims.stage_documents")
        cls.stage_lodged = cls.env.ref("insurance_broker_claims.stage_lodged")
        cls.stage_assessment = cls.env.ref("insurance_broker_claims.stage_assessment")
        cls.stage_dv_review = cls.env.ref("insurance_broker_claims.stage_dv_review")
        cls.stage_settled = cls.env.ref("insurance_broker_claims.stage_settled")
        cls.stage_repudiated = cls.env.ref("insurance_broker_claims.stage_repudiated")

        # The finance module gates these partner flags by domain, so set them
        # explicitly the way a broker would.
        cls.client = cls.env["res.partner"].create(
            {"name": "Apex Logistics Ltd", "is_insured": True}
        )
        cls.underwriter = cls.env["res.partner"].create(
            {"name": "SafeGuard Insurance Co.", "is_underwriter": True}
        )
        cls.garage = cls.env["res.partner"].create({"name": "Nairobi Body Repairs"})

        # A 12 month motor policy that started 6 months ago, so exactly half the
        # premium has been earned. Deterministic loss ratio math depends on this.
        cls.today = fields.Date.context_today(cls.env.user)
        cls.policy_start = cls.today - timedelta(days=182)
        cls.policy_end = cls.today + timedelta(days=183)
        cls.policy = cls._make_policy("POL/2026/00001", gross_premium=12000.0, bind=True)

    @classmethod
    def _make_policy(cls, name, gross_premium, bind=True, insurance_class="motor", **extra):
        """Create a policy in the finance module's book, optionally bound."""
        vals = {
            "name": name,
            "client_id": cls.client.id,
            "underwriter_id": cls.underwriter.id,
            "insurance_class": insurance_class,
            "start_date": cls.policy_start,
            "end_date": cls.policy_end,
            "gross_premium": gross_premium,
        }
        vals.update(extra)
        policy = cls.policy_model.create(vals)
        if bind:
            policy.action_bind()
        return policy

    def _create_claim(self, **overrides):
        vals = {
            "policy_id": self.policy.id,
            "date_of_loss": fields.Datetime.now() - timedelta(days=3),
            "loss_description": "Rear-end collision on Mombasa Road.",
            "estimated_amount": 5000.0,
        }
        vals.update(overrides)
        return self.claim_model.create(vals)

    def _receive_all_required(self, claim):
        claim.document_ids.filtered("is_required").action_mark_received()
        return True

    def _settle(self, claim, settled_amount):
        """Drive a claim all the way to Settled with a given payout."""
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_assessment.id})
        claim.write(
            {"stage_id": self.stage_settled.id, "settled_amount": settled_amount}
        )
        return claim
