from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class InsuranceClaimStage(models.Model):
    _name = "insurance.claim.stage"
    _description = "Insurance Claim Stage"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(
        string="Fold in Kanban",
        help="Collapsed column in the claims board.",
    )
    is_closed = fields.Boolean(
        string="Closed Stage",
        help="Terminal stage: the claim is finished and will no longer age against its SLA.",
    )
    requires_documents = fields.Boolean(
        string="Requires Complete Checklist",
        help="A claim may only enter this stage once every required document on "
        "its checklist has been received. Set on the 'Lodged with Insurer' stage.",
    )
    counts_as_incurred = fields.Boolean(
        string="Counts as Incurred",
        help="Include this stage's amount in the loss ratio. Enable for Under Assessment, "
        "Discharge Voucher and Repudiated so the claim still reserves while contested. "
        "Leave off for intake and document-gathering stages.",
    )
    sla_hours = fields.Integer(
        string="SLA (Hours)",
        help="Target turnaround in this stage, in working hours. Zero disables the clock.",
    )
    working_days = fields.Integer(
        string="Working Days",
        default=5,
        help="Days per week counted as working time. 5 skips Saturday and Sunday, "
        "7 counts calendar hours, 6 skips Sunday only.",
    )
    active = fields.Boolean(default=True)

    _check_sla_hours_positive = models.Constraint(
        "CHECK(sla_hours >= 0)",
        "SLA hours cannot be negative.",
    )
    _check_working_days_range = models.Constraint(
        "CHECK(working_days >= 1 AND working_days <= 7)",
        "Working days must be between 1 and 7.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_sla_config(vals.get("sla_hours"), vals.get("working_days"))
            self._validate_closed_counts(vals.get("is_closed"), vals.get("counts_as_incurred"))
        return super().create(vals_list)

    def write(self, vals):
        if "sla_hours" in vals or "working_days" in vals:
            self._validate_sla_config(
                vals.get("sla_hours", self.sla_hours),
                vals.get("working_days", self.working_days),
            )
        if "is_closed" in vals or "counts_as_incurred" in vals:
            self._validate_closed_counts(
                vals.get("is_closed", self.is_closed),
                vals.get("counts_as_incurred", self.counts_as_incurred),
            )
        return super().write(vals)

    @api.model
    def _validate_sla_config(self, sla_hours, working_days):
        if sla_hours is not None and sla_hours < 0:
            raise ValidationError(_("SLA hours cannot be negative."))
        if working_days is not None and not 1 <= working_days <= 7:
            raise ValidationError(_("Working days must be between 1 and 7."))

    @api.model
    def _validate_closed_counts(self, is_closed, counts_as_incurred):
        if is_closed and not counts_as_incurred:
            raise ValidationError(
                _(
                    "A closed stage must count as incurred. A settled or repudiated "
                    "claim stops accruing reserve, so leaving this off would understate "
                    "the loss ratio."
                )
            )

    @api.constrains("is_closed", "counts_as_incurred")
    def _check_closed_counts(self):
        for rec in self:
            self._validate_closed_counts(rec.is_closed, rec.counts_as_incurred)
