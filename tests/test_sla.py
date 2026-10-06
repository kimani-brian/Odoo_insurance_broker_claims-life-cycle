from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .common import ClaimsTestCommon


class TestSla(ClaimsTestCommon):
    def test_01_same_day_completion_does_not_touch_the_weekend(self):
        # Friday 10:00 + 4h finishes on the Friday, so no weekend arithmetic runs.
        start = datetime(2026, 1, 9, 10, 0)  # a Friday
        result = self.claim_model._add_working_hours(start, 4, working_days=5)
        self.assertEqual(result, datetime(2026, 1, 9, 14, 0))

    def test_02_intraday_spill_rolls_over_the_weekend(self):
        # Friday 23:00 + 4h: one hour on the Friday, Saturday and Sunday skipped,
        # the remaining three on the Monday.
        start = datetime(2026, 1, 9, 23, 0)
        result = self.claim_model._add_working_hours(start, 4, working_days=5)
        self.assertEqual(result, datetime(2026, 1, 12, 3, 0))

    def test_03_saturday_is_a_working_day_on_a_six_day_week(self):
        start = datetime(2026, 1, 10, 10, 0)  # a Saturday
        result = self.claim_model._add_working_hours(start, 4, working_days=6)
        self.assertEqual(result, datetime(2026, 1, 10, 14, 0))

    def test_04_sunday_is_skipped_on_a_six_day_week(self):
        # Sunday is a non-working day in full, so the clock resumes at Monday midnight.
        start = datetime(2026, 1, 11, 10, 0)  # a Sunday
        result = self.claim_model._add_working_hours(start, 4, working_days=6)
        self.assertEqual(result, datetime(2026, 1, 12, 4, 0))

    def test_05_seven_day_week_is_plain_calendar_time(self):
        start = datetime(2026, 1, 10, 10, 0)  # a Saturday
        result = self.claim_model._add_working_hours(start, 4, working_days=7)
        self.assertEqual(result, datetime(2026, 1, 10, 14, 0))

    def test_06_zero_hours_leaves_the_deadline_unset(self):
        claim = self._create_claim()
        claim.write({"stage_id": self.stage_settled.id})
        self.assertEqual(claim.sla_deadline, False)

    def test_07_deadline_advances_on_stage_change(self):
        claim = self._create_claim()
        first_deadline = claim.sla_deadline
        self.assertTrue(first_deadline)
        claim.write({"stage_id": self.stage_documents.id})
        self.assertNotEqual(claim.sla_deadline, first_deadline)
        self.assertGreater(claim.sla_deadline, first_deadline)

    def test_08_stage_change_resets_the_breach_flag(self):
        claim = self._create_claim()
        claim.is_sla_breached = True
        claim.write({"stage_id": self.stage_documents.id})
        self.assertFalse(claim.is_sla_breached)

    def test_09_cron_flags_overdue_claims(self):
        claim = self._create_claim()
        past = fields.Datetime.now() - timedelta(days=3)
        claim.write({"sla_deadline": past})
        self.assertFalse(claim.is_sla_breached)

        flagged = self.claim_model._cron_flag_sla_breaches()
        self.assertEqual(flagged, 1)
        self.assertTrue(claim.is_sla_breached)

    def test_10_cron_ignores_claims_inside_their_sla(self):
        claim = self._create_claim()
        future = fields.Datetime.now() + timedelta(days=3)
        claim.write({"sla_deadline": future})
        self.assertEqual(self.claim_model._cron_flag_sla_breaches(), 0)
        self.assertFalse(claim.is_sla_breached)

    def test_11_cron_ignores_closed_stages(self):
        claim = self._create_claim()
        self._receive_all_required(claim)
        claim.write({"stage_id": self.stage_lodged.id})
        claim.write({"stage_id": self.stage_settled.id, "settled_amount": 100.0})
        claim.write({"sla_deadline": fields.Datetime.now() - timedelta(days=3)})
        self.assertEqual(self.claim_model._cron_flag_sla_breaches(), 0)

    def test_12_cron_does_not_reflag_the_same_claim(self):
        claim = self._create_claim()
        claim.write({"sla_deadline": fields.Datetime.now() - timedelta(days=3)})
        self.assertEqual(self.claim_model._cron_flag_sla_breaches(), 1)
        self.assertEqual(self.claim_model._cron_flag_sla_breaches(), 0)

    def test_13_hours_remaining_is_negative_once_overdue(self):
        claim = self._create_claim()
        claim.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=5)})
        self.assertLess(claim.sla_hours_remaining, 0)

    def test_14_stage_rejects_invalid_sla_configuration(self):
        with self.assertRaises(ValidationError):
            self.stage_model.create({"name": "Bad", "sla_hours": -5})
        with self.assertRaises(ValidationError):
            self.stage_model.create({"name": "Bad", "working_days": 9})

    def test_15_closed_stage_must_count_as_incurred(self):
        with self.assertRaises(ValidationError):
            self.stage_model.create(
                {"name": "Closed but not reserving", "is_closed": True}
            )
