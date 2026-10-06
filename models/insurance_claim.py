from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .constants import COVER_STATES, INSURANCE_CLASSES


class InsuranceClaim(models.Model):
    _name = "insurance.claim"
    _description = "Insurance Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_of_loss desc, id desc"

    # --- Identification ---
    name = fields.Char(
        string="Claim Reference",
        required=True,
        copy=False,
        index=True,
        tracking=True,
        default=lambda self: _("New"),
    )
    insurer_claim_ref = fields.Char(
        string="Insurer Claim Reference",
        copy=False,
        index=True,
        tracking=True,
        help="The underwriter's own file or claim number.",
    )

    # --- Links ---
    policy_id = fields.Many2one(
        "insurance.policy",
        string="Policy",
        ondelete="set null",
        copy=False,
        index=True,
        tracking=True,
        help="Policy from the insurance_broker_finance policy book. A claim can "
        "only be notified against a policy that is bound or invoiced.",
    )
    client_id = fields.Many2one(
        "res.partner",
        string="Insured Client",
        ondelete="set null",
        index=True,
        tracking=True,
    )
    underwriter_id = fields.Many2one(
        "res.partner",
        string="Underwriter / Insurer",
        ondelete="set null",
        index=True,
        tracking=True,
    )
    insurance_class = fields.Selection(
        INSURANCE_CLASSES,
        string="Business Class",
        index=True,
        tracking=True,
        help="Snapshot of the policy's class at intake. Drives which document "
        "checklist was loaded.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Claim Handler",
        default=lambda self: self.env.user,
        index=True,
        tracking=True,
        help="Broker accountable for progressing this claim.",
    )
    active = fields.Boolean(default=True)

    # --- Incident ---
    date_of_loss = fields.Datetime(
        string="Date of Loss",
        required=True,
        index=True,
        tracking=True,
    )
    date_fnol = fields.Datetime(
        string="FNOL Notified",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        help="First notification of loss received from the client.",
    )
    loss_description = fields.Text(required=True)
    incident_location = fields.Char()
    notes = fields.Text()

    # --- Financials ---
    estimated_amount = fields.Monetary(
        string="Estimated Loss",
        currency_field="currency_id",
        default=0.0,
        help="Broker's opening reserve before any assessment.",
    )
    assessed_amount = fields.Monetary(
        string="Assessed Amount",
        currency_field="currency_id",
        default=0.0,
        help="Loss adjuster's recommended settlement, before excess.",
    )
    excess_amount = fields.Monetary(
        string="Policy Excess",
        currency_field="currency_id",
        default=0.0,
        help="Deductible borne by the client and deducted from the payout.",
    )
    settled_amount = fields.Monetary(
        string="Final Settlement",
        currency_field="currency_id",
        default=0.0,
        help="Net amount actually approved and paid.",
    )
    net_offer_amount = fields.Monetary(
        string="Net Offer",
        compute="_compute_net_offer",
        currency_field="currency_id",
        help="Assessed amount less policy excess.",
    )
    incurred_amount = fields.Monetary(
        string="Incurred Amount",
        compute="_compute_incurred_amount",
        store=True,
        currency_field="currency_id",
        help="Amount this claim contributes to the loss ratio. Escalates as the "
        "claim is assessed and settles at the final amount.",
    )

    # --- Workflow / SLA ---
    stage_id = fields.Many2one(
        "insurance.claim.stage",
        string="Stage",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        default=lambda self: self._default_stage_id(),
    )
    stage_entry_date = fields.Datetime(
        string="Stage Entered On",
        readonly=True,
        copy=False,
        tracking=True,
    )
    sla_deadline = fields.Datetime(
        string="SLA Deadline",
        compute="_compute_sla_deadline",
        store=True,
        readonly=False,
    )
    is_sla_breached = fields.Boolean(
        string="SLA Breached",
        default=False,
        index=True,
        copy=False,
        help="Set automatically by the SLA monitor when the deadline passes.",
    )
    sla_hours_remaining = fields.Float(
        string="Hours to SLA",
        compute="_compute_sla_hours_remaining",
        help="Negative once the deadline has passed.",
    )

    # --- Children ---
    document_ids = fields.One2many(
        "insurance.claim.document",
        "claim_id",
        string="Documents",
        copy=True,
    )
    service_provider_ids = fields.One2many(
        "insurance.claim.service.provider",
        "claim_id",
        string="Service Providers",
        copy=True,
    )
    required_document_count = fields.Integer(compute="_compute_document_progress", store=True)
    received_document_count = fields.Integer(compute="_compute_document_progress", store=True)
    missing_document_count = fields.Integer(compute="_compute_document_progress", store=True)
    is_documents_complete = fields.Boolean(compute="_compute_document_progress", store=True)
    missing_document_names = fields.Char(compute="_compute_missing_document_names")

    _check_amounts_non_negative = models.Constraint(
        "CHECK(estimated_amount >= 0 AND assessed_amount >= 0 "
        "AND excess_amount >= 0 AND settled_amount >= 0)",
        "Claim amounts cannot be negative.",
    )
    _check_fnol_after_loss = models.Constraint(
        "CHECK(date_fnol IS NULL OR date_of_loss IS NULL OR date_fnol >= date_of_loss)",
        "The FNOL date cannot be earlier than the date of loss.",
    )

    # ------------------------------------------------------------------
    # Defaults & creation
    # ------------------------------------------------------------------
    @api.model
    def _default_stage_id(self):
        return self.env["insurance.claim.stage"].search(
            [("sequence", "=", 10)],
            limit=1,
        ) or self.env["insurance.claim.stage"].search([], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("insurance.claim") or _("New")
                )
            if not vals.get("stage_entry_date"):
                vals["stage_entry_date"] = fields.Datetime.now()
            # Inherit the policy's identity so a claim created from a policy
            # (button, RPC, import) is consistent even outside the form's onchange.
            if vals.get("policy_id"):
                self._inherit_from_policy(vals)
            # SQL CHECK constraints are evaluated by the database at INSERT, which
            # happens before @api.constrains runs, so a user typing a negative
            # amount would otherwise see a raw psycopg2 error. Validate up front to
            # raise a readable ValidationError; the CHECK stays as the backstop.
            self._validate_amounts(vals)
            self._validate_loss_dates(vals)
        claims = super().create(vals_list)
        claims._load_document_checklist()
        return claims

    @api.model
    def _inherit_from_policy(self, vals):
        """Copy client, underwriter, class and currency off the linked policy."""
        policy = self.env["insurance.policy"].browse(vals["policy_id"])
        if not policy.exists():
            raise ValidationError(_("The selected policy no longer exists."))
        if policy.state not in COVER_STATES:
            raise ValidationError(
                _(
                    "Policy %(policy)s is %(state)s. A claim can only be notified "
                    "against a policy that is bound or invoiced.",
                    policy=policy.name,
                    state=dict(policy._fields["state"].selection).get(
                        policy.state, policy.state
                    ),
                )
            )
        vals.setdefault("client_id", policy.client_id.id)
        vals.setdefault("underwriter_id", policy.underwriter_id.id)
        vals.setdefault("insurance_class", policy.insurance_class)
        vals.setdefault("company_id", policy.company_id.id)
        if not vals.get("currency_id"):
            vals["currency_id"] = policy.currency_id.id
        elif vals["currency_id"] != policy.currency_id.id:
            raise ValidationError(
                _(
                    "Policy %(policy)s is denominated in %(policy_currency)s, so the "
                    "claim must use the same currency. The loss ratio compares the "
                    "two directly and would otherwise be wrong.",
                    policy=policy.name,
                    policy_currency=policy.currency_id.name,
                )
            )

    @api.model
    def _validate_amounts(self, vals):
        for field_name in (
            "estimated_amount",
            "assessed_amount",
            "excess_amount",
            "settled_amount",
        ):
            value = vals.get(field_name)
            if value is not None and value < 0.0:
                raise ValidationError(
                    _("%(label)s cannot be negative.", label=self._fields[field_name].string)
                )

    @api.model
    def _validate_loss_dates(self, vals):
        loss = vals.get("date_of_loss")
        fnol = vals.get("date_fnol")
        if loss and fnol and fnol < loss:
            raise ValidationError(
                _("The claim cannot be notified before the loss occurred.")
            )

    def _load_document_checklist(self):
        """Seed the document checklist from the class preset, once per claim."""
        template_model = self.env["insurance.claim.document.template"]
        for rec in self:
            if rec.document_ids:
                continue
            templates = template_model._templates_for(rec.insurance_class)
            if not templates:
                continue
            rec.document_ids = [
                (
                    0,
                    0,
                    {
                        "name": t.name,
                        "sequence": t.sequence,
                        "is_required": t.is_required,
                        "description": t.description,
                    },
                )
                for t in templates
            ]
            rec.message_post(
                body=_("Loaded %(count)d document checklist item(s) from the %(klass)s preset.", count=len(templates), klass=rec.insurance_class)
            )

    @api.onchange("policy_id")
    def _onchange_policy_id(self):
        for rec in self:
            if not rec.policy_id:
                continue
            rec.client_id = rec.policy_id.client_id
            rec.underwriter_id = rec.policy_id.underwriter_id
            rec.insurance_class = rec.policy_id.insurance_class
            if rec.policy_id.currency_id:
                rec.currency_id = rec.policy_id.currency_id
    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("assessed_amount", "excess_amount")
    def _compute_net_offer(self):
        for rec in self:
            rec.net_offer_amount = max(rec.assessed_amount - rec.excess_amount, 0.0)

    @api.depends(
        "estimated_amount",
        "assessed_amount",
        "excess_amount",
        "settled_amount",
        "stage_id",
        "stage_id.counts_as_incurred",
        "stage_id.is_closed",
    )
    def _compute_incurred_amount(self):
        """Escalating reserve feeding the loss ratio.

        Stages that do not count as incurred contribute nothing, so intake and
        document-gathering never inflate the ratio. Once a claim is under
        assessment it reserves on the assessed figure net of excess. A closed
        claim settles at the amount actually paid. Repudiated claims still
        reserve, because the reserve is only released on finality.
        """
        for rec in self:
            if not rec.stage_id.counts_as_incurred:
                rec.incurred_amount = 0.0
            elif rec.stage_id.is_closed and rec.settled_amount:
                rec.incurred_amount = rec.settled_amount
            elif rec.assessed_amount:
                rec.incurred_amount = max(rec.assessed_amount - rec.excess_amount, 0.0)
            else:
                rec.incurred_amount = rec.estimated_amount

    @api.depends("stage_id", "stage_id.sla_hours", "stage_id.working_days", "stage_entry_date")
    def _compute_sla_deadline(self):
        for rec in self:
            if not rec.stage_entry_date or not rec.stage_id.sla_hours:
                rec.sla_deadline = False
            else:
                rec.sla_deadline = self._add_working_hours(
                    rec.stage_entry_date,
                    rec.stage_id.sla_hours,
                    rec.stage_id.working_days,
                )

    @api.depends("sla_deadline", "is_sla_breached")
    def _compute_sla_hours_remaining(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.sla_deadline:
                rec.sla_hours_remaining = 0.0
            else:
                rec.sla_hours_remaining = (rec.sla_deadline - now).total_seconds() / 3600.0

    @api.depends("document_ids", "document_ids.is_required", "document_ids.is_received")
    def _compute_document_progress(self):
        for rec in self:
            required = rec.document_ids.filtered("is_required")
            received = required.filtered("is_received")
            rec.required_document_count = len(required)
            rec.received_document_count = len(received)
            rec.missing_document_count = len(required) - len(received)
            rec.is_documents_complete = not (required - received)

    @api.depends("document_ids", "document_ids.is_required", "document_ids.is_received")
    def _compute_missing_document_names(self):
        # Kept separate from _compute_document_progress: mixing stored and
        # non-stored fields in one compute method triggers an ORM warning.
        for rec in self:
            missing = rec.document_ids.filtered("is_required").filtered(
                lambda d: not d.is_received
            )
            rec.missing_document_names = ", ".join(missing.mapped("name"))[:255]

    # ------------------------------------------------------------------
    # SLA helpers
    # ------------------------------------------------------------------
    @api.model
    def _add_working_hours(self, start, hours, working_days=5):
        """Advance a datetime by working hours, skipping non-working days.

        Odoo ships no working calendar, so the stage carries ``working_days``:
        5 skips Saturday and Sunday, 6 skips Sunday only, 7 is plain calendar
        time. Steps whole days at a time so long spans stay cheap.
        """
        if not start or not hours or hours <= 0:
            return start
        if working_days >= 7:
            return start + timedelta(hours=hours)
        if working_days < 1:
            working_days = 1
        rest_days = 7 - working_days
        current = start
        remaining = float(hours)
        # Hard stop: no single step can exceed 7 days, so 2000 iterations is ample.
        for _ in range(2000):
            if remaining <= 0:
                break
            weekday = current.weekday()
            if rest_days == 2 and weekday == 5:  # Saturday on a Mon-Fri week
                current = self._start_of_next_day(current)
                continue
            if rest_days >= 1 and weekday == 6:  # Sunday on any week with a rest day
                current = self._start_of_next_day(current)
                continue
            hours_left_today = self._hours_until_midnight(current)
            if remaining <= hours_left_today:
                current += timedelta(hours=remaining)
                remaining = 0.0
                break
            remaining -= hours_left_today
            current = self._start_of_next_day(current)
        return current

    @api.model
    def _start_of_next_day(self, value):
        return (value + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    @api.model
    def _hours_until_midnight(self, value):
        midnight = (value + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (midnight - value).total_seconds() / 3600.0

    @api.model
    def _cron_flag_sla_breaches(self):
        """Hourly monitor: flag overdue claims and raise an activity once."""
        now = fields.Datetime.now()
        claims = self.search(
            [
                ("sla_deadline", "!=", False),
                ("sla_deadline", "<", now),
                ("is_sla_breached", "=", False),
                ("stage_id.is_closed", "=", False),
            ]
        )
        for claim in claims:
            claim.is_sla_breached = True
            claim.message_post(
                body=_(
                    "SLA breached: the %(stage)s stage passed its %(hours)sh deadline on %(deadline)s.",
                    stage=claim.stage_id.name,
                    hours=claim.stage_id.sla_hours,
                    deadline=claim.sla_deadline,
                )
            )
            claim.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Chase insurer: %(name)s SLA breached", name=claim.name),
                note=_(
                    "This claim overran its %(stage)s target. Contact the underwriter to "
                    "confirm progress.",
                    stage=claim.stage_id.name,
                ),
                date_deadline=now + timedelta(days=1),
            )
        return len(claims)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _validate_stage_transition(self, target_stage):
        for rec in self:
            if rec.stage_id == target_stage:
                continue
            if not rec.client_id or not rec.policy_id:
                raise UserError(
                    _(
                        "Claim %(name)s must have a policy and an insured client before "
                        "moving to %(stage)s.",
                        name=rec.name,
                        stage=target_stage.name,
                    )
                )
            missing = rec.document_ids.filtered("is_required").filtered(
                lambda d: not d.is_received
            )
            if missing and target_stage.requires_documents:
                raise UserError(
                    _(
                        "Cannot move %(name)s to '%(stage)s'. These required documents "
                        "are still outstanding: %(docs)s",
                        name=rec.name,
                        stage=target_stage.name,
                        docs=", ".join(missing.mapped("name")),
                    )
                )
            if rec.stage_id.is_closed:
                raise UserError(
                    _(
                        "Claim %(name)s is in a closed stage and cannot be moved to "
                        "%(stage)s.",
                        name=rec.name,
                        stage=target_stage.name,
                    )
                )

    def action_reopen(self):
        reopen_stage = self.env["insurance.claim.stage"].search(
            [("is_closed", "=", False)], order="sequence", limit=1
        )
        if not reopen_stage:
            raise UserError(_("No open stage is configured to reopen into."))
        for rec in self:
            if not rec.stage_id.is_closed:
                raise UserError(_("Only a closed claim can be reopened."))
            # Bypass the transition guard: leaving a closed stage is the point.
            super(InsuranceClaim, rec).write({"stage_id": reopen_stage.id})
            rec._on_stage_changed()
            rec.message_post(body=_("Claim reopened into %(stage)s.", stage=reopen_stage.name))
        return True

    def action_mark_all_documents_received(self):
        for rec in self:
            rec.document_ids.filtered(lambda d: not d.is_received).action_mark_received()
        return True

    def action_view_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Documents"),
            "res_model": "insurance.claim.document",
            "view_mode": "list,form",
            "domain": [("claim_id", "=", self.id)],
            "context": {"default_claim_id": self.id},
        }

    def action_view_policy(self):
        """Open the finance module's policy record for this claim."""
        self.ensure_one()
        if not self.policy_id:
            raise UserError(_("This claim is not linked to a policy."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Policy"),
            "res_model": "insurance.policy",
            "view_mode": "form",
            "res_id": self.policy_id.id,
            "target": "current",
        }

    def action_new_claim_from_policy(self):
        """Reverse navigation: start a sibling claim on the same policy."""
        self.ensure_one()
        if not self.policy_id:
            raise UserError(_("This claim is not linked to a policy."))
        return self.policy_id.action_new_claim()

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    @api.constrains("date_of_loss", "date_fnol")
    def _check_fnol_order(self):
        for rec in self:
            if rec.date_of_loss and rec.date_fnol and rec.date_fnol < rec.date_of_loss:
                raise ValidationError(
                    _(
                        "Claim %(name)s was notified before the loss occurred.",
                        name=rec.name,
                    )
                )

    def _validate_policy_cover(self, policy, date_of_loss=None):
        """A loss is only valid against cover that is actually in force."""
        self.ensure_one()
        if not policy:
            return
        if policy.state not in COVER_STATES:
            raise ValidationError(
                _(
                    "Policy %(policy)s is %(state)s. A claim can only be notified "
                    "against a policy that is bound or invoiced.",
                    policy=policy.name,
                    state=dict(policy._fields["state"].selection).get(
                        policy.state, policy.state
                    ),
                )
            )
        loss = date_of_loss or self.date_of_loss
        if loss:
            loss_date = fields.Date.to_date(loss)
            if loss_date < policy.start_date or loss_date > policy.end_date:
                raise ValidationError(
                    _(
                        "Loss date %(loss)s falls outside the cover period of policy "
                        "%(policy)s (%(start)s to %(end)s).",
                        loss=loss_date,
                        policy=policy.name,
                        start=policy.start_date,
                        end=policy.end_date,
                    )
                )

    @api.constrains("policy_id", "date_of_loss")
    def _check_loss_within_policy(self):
        # Delegates to the same guard the create/write paths use, so there is one
        # message for one rule.
        for rec in self:
            rec._validate_policy_cover(rec.policy_id)

    def write(self, vals):
        if "stage_id" in vals and vals["stage_id"]:
            target = self.env["insurance.claim.stage"].browse(vals["stage_id"])
            for rec in self:
                rec._validate_stage_transition(target)
        if "policy_id" in vals and vals["policy_id"]:
            new_policy = self.env["insurance.policy"].browse(vals["policy_id"])
            for rec in self:
                rec._validate_policy_cover(new_policy, rec.date_of_loss)
        self._validate_amounts(vals)
        for rec in self:
            merged = {
                "date_of_loss": vals.get("date_of_loss", rec.date_of_loss),
                "date_fnol": vals.get("date_fnol", rec.date_fnol),
            }
            rec._validate_loss_dates(merged)
        result = super().write(vals)
        if "stage_id" in vals:
            self._on_stage_changed()
        return result

    def _on_stage_changed(self):
        """Stamp stage entry, reset the breach flag, re-arm the SLA."""
        for rec in self:
            rec.stage_entry_date = fields.Datetime.now()
            rec.is_sla_breached = False
            if rec.stage_id.sla_hours:
                rec.sla_deadline = rec._add_working_hours(
                    rec.stage_entry_date,
                    rec.stage_id.sla_hours,
                    rec.stage_id.working_days,
                )
            else:
                rec.sla_deadline = False
        return True

    def unlink(self):
        for rec in self:
            if not rec.stage_id.is_closed:
                raise UserError(
                    _(
                        "Claim %(name)s is still open. Move it to a closed stage "
                        "before deleting.",
                        name=rec.name,
                    )
                )
        return super().unlink()
