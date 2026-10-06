from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import ClaimsTestCommon


class TestClaimLifecycle(ClaimsTestCommon):
    def test_01_claim_gets_sequence_reference(self):
        claim = self._create_claim()
        self.assertTrue(claim.name.startswith("CLM/"), claim.name)
        self.assertNotEqual(claim.name, "New")

    def test_02_claim_defaults_to_intake_stage(self):
        claim = self._create_claim()
        self.assertEqual(claim.stage_id, self.stage_fnol)
        self.assertIsNotNone(claim.stage_entry_date)
        self.assertTrue(claim.sla_deadline)

    def test_03_claim_amounts_reject_negatives(self):
        with self.assertRaises(ValidationError):
            self.claim_model.create(
                {
                    "policy_id": self.policy.id,
                    "insurance_class": "motor",
                    "date_of_loss": fields.Datetime.now(),
                    "loss_description": "Bad data",
                    "estimated_amount": -100.0,
                }
            )

    def test_04_fnol_cannot_precede_date_of_loss(self):
        with self.assertRaises(ValidationError):
            self._create_claim(
                date_of_loss=fields.Datetime.now(),
                date_fnol=fields.Datetime.now() - timedelta(days=2),
            )

    def test_06_full_lifecycle_to_settlement(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        self.assertEqual(claim.stage_id, self.stage_lodged)

        claim.write(
            {
                "insurer_claim_ref": "CLM-SG-9981",
                "assessed_amount": 2800.0,
                "excess_amount": 300.0,
            }
        )
        self.assertAlmostEqual(claim.net_offer_amount, 2500.0, places=2)

        claim.write({"stage_id": self.stage_assessment.id})
        claim.write({"stage_id": self.stage_dv_review.id})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 2500.0})

        self.assertTrue(claim.stage_id.is_closed)
        self.assertAlmostEqual(claim.incurred_amount, 2500.0, places=2)

    def test_07_open_claim_cannot_be_deleted(self):
        claim = self._create_claim()
        with self.assertRaises(UserError):
            claim.unlink()

    def test_08_closed_claim_can_be_deleted(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 100.0})
        claim_id = claim.id
        claim.unlink()
        self.assertFalse(self.claim_model.browse(claim_id).exists())

    def test_09_closed_claim_cannot_move_to_open_stage(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 100.0})
        with self.assertRaises(UserError):
            claim.write({"stage_id": self.stage_assessment.id})

    def test_10_reopen_returns_claim_to_open_stage(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 100.0})
        claim.action_reopen()
        self.assertFalse(claim.stage_id.is_closed)
        self.assertEqual(claim.stage_id, self.stage_fnol)

    def test_11_service_providers_recorded(self):
        claim = self._create_claim()
        provider = self.env["insurance.claim.service.provider"].create(
            {
                "claim_id": claim.id,
                "partner_id": self.garage.id,
                "provider_type": "garage",
            }
        )
        self.assertEqual(provider.claim_id, claim)
        self.assertIn(provider, claim.service_provider_ids)

    def test_12_mark_all_documents_received(self):
        claim = self._create_claim()
        self.assertFalse(claim.is_documents_complete)
        claim.action_mark_all_documents_received()
        self.assertTrue(claim.is_documents_complete)
        self.assertEqual(claim.missing_document_count, 0)
