from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from psycopg2 import IntegrityError

from .common import ClaimsTestCommon


class TestLossRatio(ClaimsTestCommon):
    def test_01_earned_premium_is_pro_rated(self):
        # 12,000 premium, 182 of 365 days elapsed => about half earned.
        self.assertAlmostEqual(
            self.policy.earned_premium, 12000.0 * (182 / 365), places=2
        )

    def test_02_no_earned_premium_before_inception(self):
        future = self._make_policy(
            "POL/2027/00001",
            10000.0,
            insurance_class="fire",
            start_date=self.today + timedelta(days=30),
            end_date=self.today + timedelta(days=395),
        )
        self.assertEqual(future.earned_premium, 0.0)
        self.assertEqual(future.loss_ratio, 0.0)

    def test_03_full_premium_earned_after_expiry(self):
        expired = self._make_policy(
            "POL/2025/00001",
            10000.0,
            insurance_class="marine",
            start_date=self.today - timedelta(days=400),
            end_date=self.today - timedelta(days=35),
        )
        self.assertEqual(expired.earned_premium, 10000.0)

    def test_04_intake_does_not_reserve(self):
        claim = self._create_claim(estimated_amount=4000.0)
        self.assertEqual(claim.stage_id, self.stage_fnol)
        self.assertFalse(self.stage_fnol.counts_as_incurred)
        self.assertEqual(claim.incurred_amount, 0.0)
        self.assertEqual(self.policy.claims_incurred_total, 0.0)
        self.assertEqual(self.policy.loss_ratio, 0.0)

    def test_05_assessment_reserves_on_assessed_net_of_excess(self):
        claim = self._create_claim(estimated_amount=4000.0)
        self._receive_all_required(claim)
        claim.write(
            {
                "stage_id": self.stage_lodged.id,
                "assessed_amount": 3000.0,
                "excess_amount": 500.0,
            }
        )
        claim.write({"stage_id": self.stage_assessment.id})
        self.assertAlmostEqual(claim.incurred_amount, 2500.0, places=2)
        self.assertAlmostEqual(self.policy.claims_incurred_total, 2500.0, places=2)

    def test_06_settled_reserves_the_settled_amount(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id, "assessed_amount": 3000.0})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 2750.0})
        self.assertAlmostEqual(claim.incurred_amount, 2750.0, places=2)

    def test_07_repudiated_claim_still_reserves(self):
        """A repudiated claim keeps its reserve until the appeal is final."""
        claim = self._create_claim(estimated_amount=4000.0)
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_repudiated.id})
        self.assertTrue(self.stage_repudiated.is_closed)
        self.assertTrue(self.stage_repudiated.counts_as_incurred)
        self.assertTrue(claim.stage_id.is_closed)
        self.assertAlmostEqual(claim.incurred_amount, 4000.0, places=2)
        self.assertAlmostEqual(
            self.policy.claims_incurred_total, 4000.0, places=2
        )

    def test_08_loss_ratio_band_thresholds(self):
        """Bands are driven by the actual ratio, not by the premium.

        Settlements are sized off each policy's own earned premium so the intended
        ratio is hit regardless of how much of the term has elapsed.
        """
        banded = []
        for index, target_ratio in enumerate([10.0, 55.0, 85.0]):
            policy = self._make_policy(f"POL/2026/0010{index}", 100000.0)
            settled = policy.earned_premium * target_ratio / 100.0
            claim = self.claim_model.create(
                {
                    "policy_id": policy.id,
                    "date_of_loss": fields.Datetime.now() - timedelta(days=1),
                    "loss_description": "Band probe.",
                }
            )
            self._settle(claim, settled)
            self.assertAlmostEqual(policy.loss_ratio, target_ratio, places=1)
            banded.append(policy.loss_ratio_band)
        self.assertEqual(banded, ["low", "moderate", "adverse"])

    def test_09_partner_rollup(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id, "assessed_amount": 2000.0})
        claim.write({"stage_id": self.stage_assessment.id})
        self.assertEqual(self.client.insurance_claim_count, 1)
        self.assertAlmostEqual(
            self.client.insurance_claims_incurred_total, 2000.0, places=2
        )
        self.assertAlmostEqual(
            self.client.insurance_earned_premium_total,
            self.policy.earned_premium,
            places=2,
        )

    def test_10_loss_ratio_uses_earned_not_full_premium(self):
        """The whole point of pro-rating: a mid-term claim must not look trivial.

        A 1,500 payout against a 12,000 term premium is 12.5% on a naive
        full-premium denominator, but roughly twice that once only the elapsed
        half of the premium counts as earned.
        """
        claim = self._create_claim()
        self._settle(claim, 1500.0)

        ratio = self.policy.loss_ratio
        naive = 1500.0 / 12000.0 * 100.0
        self.assertGreater(ratio, naive)
        self.assertAlmostEqual(ratio / naive, 2.0, places=1)
        self.assertLess(ratio, 100.0)
        self.assertEqual(self.policy.loss_ratio_band, "low")

    def test_11_zero_premium_gives_zero_ratio(self):
        # finance refuses to bind a zero-premium policy, so leave it as a quotation.
        free = self._make_policy("POL/2026/00200", 0.0, bind=False)
        self.assertEqual(free.earned_premium, 0.0)
        self.assertEqual(free.loss_ratio, 0.0)

    def test_12_claim_count_tracks_children(self):
        self.assertEqual(self.policy.claim_count, 0)
        claim = self._create_claim()
        self.assertEqual(self.policy.claim_count, 1)
        self.assertIn(claim, self.policy.claim_ids)

    def test_13_incurred_never_goes_negative_on_excess(self):
        """An excess larger than the assessment must not create negative reserve."""
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write(
            {"assessed_amount": 1000.0, "excess_amount": 1500.0}
        )
        claim.write({"stage_id": self.stage_assessment.id})
        self.assertEqual(claim.net_offer_amount, 0.0)
        self.assertGreaterEqual(claim.incurred_amount, 0.0)

    def test_14_premium_cannot_be_negative(self):
        # insurance_broker_finance enforces this with a SQL CHECK only, so the
        # rejection surfaces as a database error rather than a friendly message.
        # That is a pre-existing gap in the finance module, not this one.
        blocked = False
        try:
            with self.env.cr.savepoint():
                self._make_policy("POL/2026/00300", -100.0, bind=False)
        except (ValidationError, IntegrityError):
            blocked = True
        self.assertTrue(blocked, "a negative gross premium must be refused")
