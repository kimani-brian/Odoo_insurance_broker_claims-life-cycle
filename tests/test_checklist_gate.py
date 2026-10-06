from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import ClaimsTestCommon


class TestChecklistGate(ClaimsTestCommon):
    def test_01_motor_claim_loads_motor_checklist(self):
        claim = self._create_claim()
        names = claim.document_ids.mapped("name")
        self.assertIn("Police Abstract", names)
        self.assertIn("Driver's Licence Copy", names)
        self.assertIn("Vehicle Logbook", names)
        self.assertEqual(claim.insurance_class, "motor")

    def test_02_fire_claim_loads_fire_checklist(self):
        fire_policy = self._make_policy(
            "POL/2026/00002", 20000.0, insurance_class="fire"
        )
        claim = self.env["insurance.claim"].create(
            {
                "policy_id": fire_policy.id,
                "date_of_loss": fields.Datetime.now(),
                "loss_description": "Warehouse roof leak.",
            }
        )
        names = claim.document_ids.mapped("name")
        self.assertIn("Fire Brigade Report", names)
        self.assertNotIn("Police Abstract", names)

    def test_03_class_without_preset_falls_back_to_general(self):
        claim = self._create_claim(insurance_class="life")
        names = claim.document_ids.mapped("name")
        self.assertIn("Incident / Loss Report", names)
        self.assertIn("Proof of Value", names)

    def test_04_optional_documents_do_not_block_lodging(self):
        claim = self._create_claim()
        optional = claim.document_ids.filtered(lambda d: not d.is_required)
        self.assertTrue(optional, "motor preset should include an optional estimate")
        claim.document_ids.filtered("is_required").action_mark_received()
        claim.write({"stage_id": self.stage_lodged.id})
        self.assertEqual(claim.stage_id, self.stage_lodged)

    def test_05_missing_required_document_blocks_lodging(self):
        claim = self._create_claim()
        required = claim.document_ids.filtered("is_required")
        last = required[-1]
        (required - last).action_mark_received()
        self.assertFalse(claim.is_documents_complete)
        with self.assertRaises(UserError) as ctx:
            claim.write({"stage_id": self.stage_lodged.id})
        self.assertIn(last.name, str(ctx.exception))
        self.assertEqual(claim.stage_id, self.stage_fnol)

    def test_06_error_lists_every_outstanding_document(self):
        claim = self._create_claim()
        with self.assertRaises(UserError) as ctx:
            claim.write({"stage_id": self.stage_lodged.id})
        message = str(ctx.exception)
        for doc in claim.document_ids.filtered("is_required"):
            self.assertIn(doc.name, message)

    def test_07_gate_does_not_apply_to_other_stages(self):
        claim = self._create_claim()
        # Intake -> documents -> assessment are all reachable with an empty checklist.
        claim.write({"stage_id": self.stage_documents.id})
        claim.write({"stage_id": self.stage_assessment.id})
        self.assertEqual(claim.stage_id, self.stage_assessment)

    def test_08_claim_without_policy_cannot_change_stage(self):
        claim = self.env["insurance.claim"].create(
            {
                "insurance_class": "motor",
                "date_of_loss": fields.Datetime.now(),
                "loss_description": "No policy linked.",
            }
        )
        with self.assertRaises(UserError):
            claim.write({"stage_id": self.stage_documents.id})

    def test_09_document_progress_counters(self):
        claim = self._create_claim()
        required = claim.document_ids.filtered("is_required")
        self.assertEqual(claim.required_document_count, len(required))
        self.assertEqual(claim.received_document_count, 0)
        required[:1].action_mark_received()
        self.assertEqual(claim.received_document_count, 1)
        self.assertEqual(claim.missing_document_count, len(required) - 1)

    def test_10_received_requires_a_date(self):
        claim = self._create_claim()
        doc = claim.document_ids.filtered("is_required")[0]
        with self.assertRaises(ValidationError):
            doc.write({"is_received": True, "received_date": False})

    def test_11_unreceived_cannot_keep_a_date(self):
        claim = self._create_claim()
        doc = claim.document_ids.filtered("is_required")[0]
        with self.assertRaises(ValidationError):
            doc.write({"is_received": False, "received_date": "2026-01-01"})

    def test_12_mark_outstanding_clears_state(self):
        claim = self._create_claim()
        required = claim.document_ids.filtered("is_required")
        required.action_mark_received()
        self.assertTrue(claim.is_documents_complete)
        required.action_mark_outstanding()
        self.assertFalse(claim.is_documents_complete)
        self.assertEqual(claim.received_document_count, 0)
