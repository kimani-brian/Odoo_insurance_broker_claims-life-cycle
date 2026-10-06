"""Integration tests for the link between claims and the finance policy book.

Covers the rules that only exist because the two modules are joined:
cover-state gating, claim/policy guards, and loss ratio flowing back onto
the finance policy.
"""

from datetime import datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import ClaimsTestCommon


class TestPolicyIntegration(ClaimsTestCommon):
    # --- creating a claim from an existing policy ---------------------
    def test_01_claim_inherits_identity_from_the_policy(self):
        claim = self._create_claim()
        self.assertEqual(claim.policy_id, self.policy)
        self.assertEqual(claim.client_id, self.policy.client_id)
        self.assertEqual(claim.underwriter_id, self.policy.underwriter_id)
        self.assertEqual(claim.insurance_class, self.policy.insurance_class)
        self.assertEqual(claim.currency_id, self.policy.currency_id)
        self.assertEqual(claim.company_id, self.policy.company_id)

    def test_02_claim_created_from_policy_button_action(self):
        action = self.policy.action_new_claim()
        self.assertEqual(action["res_model"], "insurance.claim")
        ctx = action["context"]
        self.assertEqual(ctx["default_policy_id"], self.policy.id)
        self.assertEqual(ctx["default_client_id"], self.policy.client_id.id)
        self.assertEqual(ctx["default_underwriter_id"], self.policy.underwriter_id.id)
        self.assertEqual(action["domain"], [("policy_id", "=", self.policy.id)])

    def test_03_no_policy_duplication(self):
        """The claims module must not keep its own copy of the policy."""
        self.assertNotIn(
            "insurance.claim.policy",
            self.env.registry.models,
            "the standalone policy snapshot must be gone",
        )
        # The claim's policy is the finance module's record, not a copy.
        self.assertEqual(self.claim_model._fields["policy_id"].comodel_name, "insurance.policy")

    # --- cover-state gating ------------------------------------------
    def test_04_cannot_claim_against_a_draft_quotation(self):
        draft = self._make_policy("POL/2026/00009", 10000.0, bind=False)
        self.assertEqual(draft.state, "draft")
        with self.assertRaises(ValidationError) as ctx:
            self.claim_model.create(
                {
                    "policy_id": draft.id,
                    "date_of_loss": fields.Datetime.now(),
                    "loss_description": "Loss on a quotation.",
                }
            )
        self.assertIn("bound or invoiced", str(ctx.exception))

    def test_05_cannot_claim_against_a_cancelled_policy(self):
        cancelled = self._make_policy("POL/2026/00010", 10000.0, bind=False)
        cancelled.action_cancel()
        with self.assertRaises(ValidationError):
            self.claim_model.create(
                {
                    "policy_id": cancelled.id,
                    "date_of_loss": fields.Datetime.now(),
                    "loss_description": "Loss after cancellation.",
                }
            )

    def test_06_claim_allowed_on_a_bound_policy(self):
        draft = self._make_policy("POL/2026/00011", 10000.0, bind=False)
        draft.action_bind()
        claim = self.claim_model.create(
            {
                "policy_id": draft.id,
                "date_of_loss": fields.Datetime.now(),
                "loss_description": "Loss on a bound policy.",
            }
        )
        self.assertEqual(claim.policy_id, draft)

    def test_07_repointing_a_claim_to_a_draft_policy_is_blocked(self):
        draft = self._make_policy("POL/2026/00012", 10000.0, bind=False)
        claim = self._create_claim()
        with self.assertRaises(ValidationError):
            claim.write({"policy_id": draft.id})

    def test_08_new_claim_button_blocked_on_a_draft_policy(self):
        draft = self._make_policy("POL/2026/00013", 10000.0, bind=False)
        with self.assertRaises(UserError):
            draft.action_new_claim()

    def test_09_loss_outside_the_cover_period_is_blocked(self):
        with self.assertRaises(ValidationError) as ctx:
            self._create_claim(
                date_of_loss=fields.Datetime.now() - timedelta(days=400)
            )
        self.assertIn("falls outside the cover period", str(ctx.exception))

    def test_10_loss_on_the_first_day_of_cover_is_accepted(self):
        claim = self._create_claim(
            date_of_loss=datetime.combine(self.policy.start_date, time.min)
        )
        self.assertEqual(claim.policy_id, self.policy)

    # --- currency ----------------------------------------------------
    def test_11_claim_currency_defaults_to_the_policy_currency(self):
        claim = self._create_claim()
        self.assertEqual(claim.currency_id, self.policy.currency_id)

    def test_12_mismatched_claim_currency_is_rejected(self):
        other = (
            self.env["res.currency"].search(
                [("id", "!=", self.policy.currency_id.id)], limit=1
            )
            or self.env["res.currency"].create(
                {"name": "ZZZ", "symbol": "Z", "rounding": 0.01}
            )
        )
        with self.assertRaises(ValidationError) as ctx:
            self.claim_model.create(
                {
                    "policy_id": self.policy.id,
                    "currency_id": other.id,
                    "date_of_loss": fields.Datetime.now(),
                    "loss_description": "Mismatched currency.",
                }
            )
        self.assertIn("same currency", str(ctx.exception))

    # --- policy-side guards ------------------------------------------
    def test_13_policy_cannot_be_deleted_while_claims_exist(self):
        """Deletion is blocked, and finance's own state rule takes precedence.

        A bound policy is not deletable at all, so finance's state guard answers
        first. The claims-specific message is reachable on the cancel step, which
        is the action a broker actually needs to unblock.
        """
        self._create_claim()
        with self.assertRaises(UserError):
            self.policy.unlink()
        self.assertTrue(self.policy.exists())
        with self.assertRaises(UserError) as ctx:
            self.policy.action_cancel()
        self.assertIn("open claim", str(ctx.exception))

    def test_13b_unlink_hook_blocks_a_cancelled_policy_that_carries_claims(self):
        """Once finance's own rules are satisfied, the claims hook still refuses.

        This is the only path where the unlink hook is the only thing standing
        between the user and a deleted case file, so it is asserted explicitly.
        """
        claim = self._create_claim()
        self._settle(claim, 1000.0)
        # No open claims left, so cancelling is allowed.
        self.policy.action_cancel()
        self.assertEqual(self.policy.state, "cancelled")

        with self.assertRaises(UserError) as ctx:
            self.policy.unlink()
        self.assertIn("referenced by 1 claim", str(ctx.exception))
        self.assertTrue(self.policy.exists())

    def test_13c_unlink_succeeds_once_the_claims_are_gone(self):
        claim = self._create_claim()
        self._settle(claim, 1000.0)
        self.policy.action_cancel()
        claim.unlink()
        self.policy.unlink()
        self.assertFalse(self.policy.exists())

    def test_14_policy_cannot_be_cancelled_while_claims_are_open(self):
        self._create_claim()
        self.assertEqual(self.policy.open_claim_count, 1)
        with self.assertRaises(UserError) as ctx:
            self.policy.action_cancel()
        self.assertIn("open claim", str(ctx.exception))

    def test_15_policy_can_be_cancelled_once_claims_are_closed(self):
        claim = self._create_claim()
        self._settle(claim, 1000.0)
        self.assertEqual(self.policy.open_claim_count, 0)
        self.policy.action_cancel()
        self.assertEqual(self.policy.state, "cancelled")

    def test_16_finance_own_guards_still_apply(self):
        """The claims addon must not wrap finance's workflow methods."""
        finance = "odoo.addons.insurance_broker_finance.models.insurance_policy"
        policy_cls = type(self.policy)
        for method in ("unlink", "action_cancel", "action_bind", "action_draft"):
            defined_in = getattr(policy_cls, method).__module__
            self.assertEqual(
                defined_in,
                finance,
                f"insurance_broker_claims must not override {method}; "
                f"it is defined in {defined_in}",
            )

    def test_17_claims_only_implements_the_extension_hooks(self):
        """The integration surface is the two no-op hooks, nothing more."""
        policy_cls = type(self.policy)
        claims = "odoo.addons.insurance_broker_claims.models.insurance_policy"
        for hook in ("_check_unlink_dependents", "_check_cancel_dependents"):
            self.assertEqual(
                getattr(policy_cls, hook).__module__,
                claims,
                f"{hook} should be implemented by the claims addon",
            )

    def test_18_hooks_permit_the_operations_when_nothing_depends(self):
        """With no claims, the hooks must return a falsy value so finance lets
        the operation through."""
        self.assertFalse(self.policy._check_unlink_dependents())
        self.assertFalse(self.policy._check_cancel_dependents())

    def test_19_hooks_return_a_blocking_message_once_claims_exist(self):
        claim = self._create_claim()
        self.assertIn("referenced by 1 claim", self.policy._check_unlink_dependents())
        self.assertIn("1 open claim", self.policy._check_cancel_dependents())

        self._settle(claim, 1000.0)
        self.assertIn("referenced by 1 claim", self.policy._check_unlink_dependents())
        self.assertFalse(
            self.policy._check_cancel_dependents(),
            "a closed claim must no longer block cancellation",
        )

    # --- analytics flow back onto the policy -------------------------
    def test_20_analystics_flow_back_onto_the_policy(self):
        self.assertEqual(self.policy.claim_count, 0)
        open_claim = self._create_claim()
        self.assertEqual(self.policy.claim_count, 1)
        self.assertEqual(self.policy.open_claim_count, 1)

        closed_claim = self._create_claim(
            loss_description="Second, settled loss."
        )
        self._settle(closed_claim, 2000.0)
        self.assertEqual(self.policy.claim_count, 2)
        self.assertEqual(self.policy.open_claim_count, 1)
        self.assertIn(open_claim, self.policy.claim_ids)

    def test_21_earned_premium_pro_rated_on_the_finance_policy(self):
        self.assertAlmostEqual(
            self.policy.earned_premium, 12000.0 * (182 / 365), places=2
        )

    def test_22_settling_a_claim_updates_the_policy_loss_ratio(self):
        claim = self._create_claim()
        self.assertEqual(self.policy.loss_ratio, 0.0)
        self._settle(claim, 1500.0)
        self.assertAlmostEqual(self.policy.claims_incurred_total, 1500.0, places=2)
        self.assertGreater(self.policy.loss_ratio, 1500.0 / 12000.0 * 100.0)
        self.assertEqual(self.policy.loss_ratio_band, "low")

    def test_23_policy_view_claims_action(self):
        claim = self._create_claim()
        action = self.policy.action_view_claims()
        self.assertEqual(action["res_model"], "insurance.claim")
        self.assertEqual(action["domain"], [("policy_id", "=", self.policy.id)])
        self.assertIn(claim, self.policy.claim_ids)

    def test_24_partner_rollup_reads_the_finance_policy_book(self):
        self.assertIn(self.policy, self.client.insurance_claim_policy_ids)
        claim = self._create_claim()
        self._settle(claim, 1500.0)
        self.assertEqual(self.client.insurance_claim_count, 1)
        self.assertAlmostEqual(
            self.client.insurance_claims_incurred_total, 1500.0, places=2
        )
        self.assertAlmostEqual(
            self.client.insurance_earned_premium_total,
            self.policy.earned_premium,
            places=2,
        )

    def test_25_deleting_the_policy_nulls_the_claim_link(self):
        """Finance blocks deleting a bound policy, so force it at the SQL level to
        prove the FK is SET NULL and the claim survives as a case file."""
        claim = self._create_claim()
        self._settle(claim, 1500.0)
        self.assertAlmostEqual(self.policy.claims_incurred_total, 1500.0, places=2)

        self.env.cr.execute(
            "DELETE FROM insurance_policy WHERE id = %s", (self.policy.id,)
        )
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT policy_id FROM insurance_claim WHERE id = %s", (claim.id,)
        )
        self.assertIsNone(self.env.cr.fetchone()[0])
        self.assertTrue(claim.exists())
        # The partner figure must not silently drop when the policy disappears.
        self.assertAlmostEqual(
            self.client.insurance_claims_incurred_total, 1500.0, places=2
        )
