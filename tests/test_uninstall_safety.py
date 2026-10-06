from odoo import fields
from odoo.exceptions import UserError, ValidationError
from psycopg2 import IntegrityError

from .common import ClaimsTestCommon


class TestUninstallSafety(ClaimsTestCommon):
    def test_01_claims_module_owns_no_policy_table(self):
        """The claims module must not duplicate the finance policy book."""
        self.env.cr.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'insurance_claim_policy'"
        )
        self.assertFalse(
            self.env.cr.fetchall(),
            "insurance_claim_policy must not exist: the finance module owns policies",
        )
        # insurance.policy is the finance module's model; this module only adds
        # the claims analytics on top of it.
        policy_model = self.env["insurance.policy"]
        for field_name in ("claim_ids", "claim_count", "earned_premium", "loss_ratio"):
            self.assertIn(field_name, policy_model._fields)
        self.assertNotIn(
            "gross_premium",
            self.env["insurance.claim"]._fields,
            "claims must not redefine finance fields",
        )

    def test_02_claim_survives_policy_deletion_and_link_is_nulled(self):
        claim = self._create_claim()
        self._settle(claim, 1500.0)
        claim_id = claim.id

        # The finance module blocks deleting a bound policy and the claims module
        # blocks it while claims exist, so force the delete at the SQL level to
        # prove the FK behaviour a real uninstall would rely on.
        self.env.cr.execute(
            "DELETE FROM insurance_policy WHERE id = %s", (self.policy.id,)
        )
        self.env.invalidate_all()

        claim = self.claim_model.browse(claim_id)
        self.assertTrue(claim.exists(), "claim must survive policy deletion")
        self.assertFalse(claim.policy_id, "policy link must be nulled, not cascaded")
        self.assertAlmostEqual(claim.incurred_amount, 1500.0, places=2)

    def test_03_claim_policy_fk_is_set_null_in_the_database(self):
        claim = self._create_claim()
        claim_id, policy_id = claim.id, self.policy.id
        self.env.cr.execute(
            "DELETE FROM insurance_policy WHERE id = %s", (policy_id,)
        )
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT policy_id FROM insurance_claim WHERE id = %s", (claim_id,)
        )
        row = self.env.cr.fetchone()
        self.assertIsNone(row[0], "claim.policy_id must be SET NULL, not cascade")

    def test_04_deleting_a_client_is_blocked_while_policies_exist(self):
        """finance.policy.client_id is required, so it must be ondelete='restrict'."""
        policy_id = self.policy.id
        self._create_claim()
        blocked = False
        try:
            with self.env.cr.savepoint():
                self.client.unlink()
        except (UserError, ValidationError, IntegrityError):
            blocked = True
        self.assertTrue(blocked, "deleting a client with policies must be refused")
        self.assertTrue(self.policy_model.browse(policy_id).exists())
        self.assertTrue(self.client.exists())

    def test_05_deleting_a_claim_cascades_to_its_children(self):
        claim = self._create_claim()
        doc_ids = claim.document_ids.ids
        self.assertTrue(doc_ids)

        self._settle(claim, 100.0)
        claim.unlink()

        docs = self.env["insurance.claim.document"].browse(doc_ids)
        self.assertFalse(docs.exists(), "checklist lines are internal and cascade")

    def test_06_deleting_a_partner_with_no_engagement_succeeds(self):
        stray = self.env["res.partner"].create({"name": "Never Engaged Ltd"})
        stray.unlink()
        self.assertFalse(stray.exists())

    def test_07_attachment_link_is_optional(self):
        claim = self._create_claim()
        doc = claim.document_ids.filtered("is_required")[0]
        attachment = self.env["ir.attachment"].create(
            {
                "name": "police-abstract.pdf",
                "res_model": "insurance.claim.document",
                "res_id": doc.id,
            }
        )
        doc.attachment_id = attachment
        self.assertEqual(doc.attachment_id, attachment)

        self.env["ir.attachment"].search([("id", "=", attachment.id)]).unlink()
        self.assertFalse(doc.attachment_id, "attachment link must null out")

    def test_08_core_partner_table_is_untouched(self):
        """No stored compute is written onto res_partner, so uninstalling leaves the
        core table alone and triggers no recompute on partner records.

        The One2many fields are excluded on purpose: an o2m stores its column on the
        child table (insurance_claim / insurance_policy), not on res_partner.
        """
        for field_name in (
            "insurance_loss_ratio",
            "insurance_earned_premium_total",
            "insurance_claims_incurred_total",
            "insurance_claim_count",
            "insurance_loss_ratio_band",
        ):
            self.assertFalse(
                self.client._fields[field_name].store,
                f"res.partner.{field_name} must not be stored",
            )
        for field_name in ("insurance_claim_ids", "insurance_claim_policy_ids"):
            self.assertTrue(
                self.client._fields[field_name].comodel_name.startswith(
                    "insurance."
                ),
                f"{field_name} must point at an insurance model",
            )

    def test_09_no_insurance_tables_reference_core_with_cascade(self):
        """Every FK from an insurance_claim* table onto a core table must not
        cascade, so uninstalling never deletes core records."""
        self.env.cr.execute(
            """
            SELECT c.relname, a.attname, con.confdeltype
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_attribute a ON a.attrelid = con.conrelid
                                AND a.attnum = ANY(con.conkey)
            JOIN pg_class core ON core.oid = con.confrelid
            JOIN pg_namespace n ON n.oid = core.relnamespace
            WHERE con.contype = 'f'
              AND c.relname LIKE 'insurance_claim%'
              AND n.nspname = 'public'
              AND core.relname IN ('res_partner', 'res_company', 'res_currency',
                                   'res_users', 'ir_attachment')
            """
        )
        offenders = []
        checked = 0
        for table, column, deltype in self.env.cr.fetchall():
            checked += 1
            # PostgreSQL confdeltype: a = no action, r = restrict, c = cascade,
            # n = set null, d = set default. Cascade is the only unsafe value here.
            if deltype == "c":
                offenders.append((table, column, deltype))
        self.assertGreater(checked, 0, "no FKs onto core models were found at all")
        self.assertFalse(
            offenders,
            f"FKs onto core models must not cascade, found: {offenders}",
        )

    def test_10_claim_fk_onto_the_finance_policy_is_set_null(self):
        """The link to insurance.policy must be nullable, not cascading, so the
        claims module can be removed without touching the finance module."""
        self.env.cr.execute(
            """
            SELECT con.confdeltype
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_attribute a ON a.attrelid = con.conrelid
                                AND a.attnum = ANY(con.conkey)
            WHERE con.contype = 'f'
              AND c.relname = 'insurance_claim'
              AND a.attname = 'policy_id'
            """
        )
        rows = self.env.cr.fetchall()
        self.assertEqual(len(rows), 1, "expected exactly one FK on insurance_claim.policy_id")
        self.assertEqual(rows[0][0], "n", "policy_id must be ON DELETE SET NULL")

    def test_11_core_partner_table_only_gains_a_nullable_setting(self):
        """Uninstalling must not require dropping data-bearing columns from a core
        table. The one column this module adds is a nullable setting the user
        controls, which Odoo drops with the module; no analytics are stored there.
        """
        self.env.cr.execute(
            """
            SELECT column_name, is_nullable, data_type
            FROM information_schema.columns
            WHERE table_name = 'res_partner' AND column_name LIKE 'insurance%'
            ORDER BY column_name
            """
        )
        rows = self.env.cr.fetchall()
        self.assertEqual(
            [r[0] for r in rows],
            ["insurance_claims_currency_id"],
            "res_partner must only gain the reporting-currency setting",
        )
        for column, nullable, _type in rows:
            self.assertEqual(nullable, "YES", f"{column} must be nullable")
