Here is the complete **Technical Architecture Document** for **Module CL (Claims Management - RFP Section 3.7)**, designed for **Odoo 19**. 

You can save this as **`ARCHITECTURE_CLAIMS.md`**.

---

```markdown
# Technical Architecture Document: Claims Management (ARCHITECTURE_CLAIMS.md)

## System: `insurance_broker_claims` (Odoo 19.0)
* **Client Reference:** Transnep Insurance Brokers Limited
* **Specification Target:** Module CL (Claims Management — RFP 3.7: CL-001 & CL-002)
* **Cross-Module Linkage:** Module TM (Process Timelines & SLA Clocks — RFP 3.9) & Module FN (3.8)
* **Engine:** Odoo 19.0 (Python 3.12+, PostgreSQL 16+)

---

## 1. Architectural Principles & Domain Design

### 1.1. Core Design Objectives
1. **The Broker Advocacy Model:** Claims are treated as collaborative case files involving four parties: **The Insured Client**, **The Broker**, **The Underwriter**, and **Third-Party Service Providers** (Assessors, Adjusters, Garages).
2. **Dynamic Checklist Architecture:** Claims auto-generate line-of-business document checklists (e.g., motor requires police abstract and driver's license; marine requires bill of lading and survey report) that act as hard gates before lodging with the insurer.
3. **SLA & Timeline Memory (TM-001/TM-002 Bridge):** Every stage transition is timestamped, tracking business-hour SLA clocks (e.g., "Time to file FNOL", "Time to receive Assessor Report", "Time to issue Discharge Voucher").
4. **Loss Ratio & Actuarial Intelligence (CL-002):** Automated calculation of client loss ratios directly on policies and partner profiles to empower broker negotiations during annual policy renewals.
5. **Zero-Breakage Decoupling:** Standalone custom tables (`insurance_claim_*`). Any linkage to `insurance.policy` or `res.partner` uses `ondelete='set null'` or `ondelete='cascade'` on internal checklist items.

---

## 2. High-Level Component Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION LAYER                            │
│   - Claims Visual Kanban (Stage Pipeline)                              │
│   - Document Matrix & Drag-and-Drop Checklist Console                  │
│   - Loss Ratio & Claims Experience Executive Dashboards                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                        CLAIMS BUSINESS ENGINE                          │
│   ┌────────────────────────┬────────────────────────────────────────┐  │
│   │ FNOL Intake & Validator│ Document Checklist Template Auto-Loader│  │
│   ├────────────────────────┼────────────────────────────────────────┤  │
│   │ SLA Working Clock &    │ Loss Ratio Compute Engine              │  │
│   │ Stage Transition Logger│ (Incurred / Earned Premium Matrix)     │  │
│   └────────────────────────┴────────────────────────────────────────┘  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                         PERSISTENCE & CORE                             │
│   - `insurance.claim` (Master Case Record)                             │
│   - `insurance.claim.document` (Checklist items & attachments)         │
│   - `insurance.claim.stage` (Configurable Kanban stages & SLA limits)  │
│   - `mail.thread` / `mail.activity` (Omnichannel email & alerts)       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema & Data Models

### 3.1. Entity-Relationship Diagram (ERD)

```
+-----------------------------------+
|  insurance_claim_stage            |
+-----------------------------------+
| id (PK)                           |
| name (VARCHAR)                    |
| sequence (INT)                    |
| sla_hours (INT)                   |
| is_closed (BOOL)                  |
+-----------------------------------+
          |
          | stage_id
          v
+-----------------------------------+        +-----------------------------------+
|  insurance_claim                  |        |  insurance_policy                 |
+-----------------------------------+        +-----------------------------------+
| id (PK)                           |        | id (PK)                           |
| name (VARCHAR, unique)            |------->| gross_premium (NUMERIC)           |
| policy_id (FK)                    |        | claims_incurred_total (COMPUTED)  |
| client_id (FK)                    |        | loss_ratio (COMPUTED %)           |
| underwriter_id (FK)               |        +-----------------------------------+
| insurer_claim_ref (VARCHAR)       |                          |
| date_of_loss (TIMESTAMP)          |                          |
| date_fnol (TIMESTAMP)             |                          |
| estimated_amount (NUMERIC)        |<-------------------------+
| assessed_amount (NUMERIC)         |
| excess_amount (NUMERIC)           |
| settled_amount (NUMERIC)          |
| sla_deadline (TIMESTAMP)          |
| is_sla_breached (BOOL)            |
+-----------------------------------+
   |                             |
   | 1                           | 1
   v *                           v *
+-----------------------------------+  +-----------------------------------+
|  insurance_claim_document         |  |  insurance_claim_service_provider|
+-----------------------------------+  +-----------------------------------+
| id (PK)                           |  | id (PK)                           |
| claim_id (FK)                     |  | claim_id (FK)                     |
| name (VARCHAR)                    |  | partner_id (FK) [Assessor/Garage] |
| is_required (BOOL)                |  | provider_type (SELECTION)         |
| is_received (BOOL)                |  | appointment_date (DATE)           |
| attachment_id (FK to ir_attachment|  | report_received_date (DATE)       |
+-----------------------------------+  +-----------------------------------+
```

---

### 3.2. Detailed Model Specifications

#### A. `insurance.claim` (The Master Claim Record)
| Column Name | SQL Type | Attributes / Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `SERIAL` | `PRIMARY KEY` | Unique ID |
| `name` | `VARCHAR(64)` | `NOT NULL`, `UNIQUE`, `INDEX` | Sequence Reference (`CLM/YYYY/XXXXX`) |
| `policy_id` | `INTEGER` | `REFERENCES insurance_policy(id) ON DELETE RESTRICT`, `NOT NULL`, `INDEX` | Associated policy |
| `client_id` | `INTEGER` | `REFERENCES res_partner(id) ON DELETE RESTRICT`, `NOT NULL`, `INDEX` | Insured Client |
| `underwriter_id` | `INTEGER` | `REFERENCES res_partner(id) ON DELETE RESTRICT`, `NOT NULL`, `INDEX` | Underwriting Insurer |
| `stage_id` | `INTEGER` | `REFERENCES insurance_claim_stage(id) ON DELETE RESTRICT`, `NOT NULL` | Current Kanban pipeline stage |
| `insurer_claim_ref`| `VARCHAR(64)` | `INDEX` | Insurer's internal file/claim number |
| `date_of_loss` | `TIMESTAMP` | `NOT NULL`, `INDEX` | Date & time incident occurred |
| `date_fnol` | `TIMESTAMP` | `NOT NULL`, `DEFAULT NOW()` | First Notification of Loss date |
| `loss_description` | `TEXT` | `NOT NULL` | Description of peril/incident |
| `incident_location`| `VARCHAR(255)`| Nullable | Physical location of accident/peril |
| `estimated_amount` | `NUMERIC(16,2)`| `DEFAULT 0.0` | Initial estimated loss reserve |
| `assessed_amount` | `NUMERIC(16,2)`| `DEFAULT 0.0` | Loss Adjuster/Assessor recommended loss |
| `excess_amount` | `NUMERIC(16,2)`| `DEFAULT 0.0` | Policy deductible deducted from payout |
| `settled_amount` | `NUMERIC(16,2)`| `DEFAULT 0.0` | Final net paid/approved settlement |
| `stage_entry_date` | `TIMESTAMP` | `DEFAULT NOW()` | Timestamp when entered current stage |
| `sla_deadline` | `TIMESTAMP` | Computed | Target deadline based on stage SLA hours |
| `is_sla_breached` | `BOOLEAN` | `DEFAULT FALSE`, `INDEX` | Flagged by cron if `NOW() > sla_deadline` |

---

#### B. `insurance.claim.stage` (Kanban Stages with SLA Limits)
* `name`: Char (e.g., `FNOL Intake`, `Document Collection`, `Lodged with Insurer`, `Under Assessment`, `Discharge Voucher Review`, `Settled`, `Repudiated/Declined`).
* `sequence`: Integer (default 10).
* `sla_hours`: Integer (Target turnaround hours in this stage, e.g., 24h for FNOL, 48h for Lodging).
* `is_closed`: Boolean (Flags final terminal stages).
* `fold`: Boolean (Folds stage visually in Kanban).

---

#### C. `insurance.claim.document` (Checklist Engine - CL-001)
* `claim_id`: Many2one(`insurance.claim`, ondelete='cascade', required=True, index=True)
* `name`: Char(string="Document Name", required=True) (e.g., "Police Abstract Form")
* `is_required`: Boolean(default=True)
* `is_received`: Boolean(default=False)
* `received_date`: Date()
* `attachment_id`: Many2one(`ir.attachment`, string="Attached File", ondelete='set null')

---

#### D. `insurance.claim.document.template` (Preconfigured Templates per Class)
* `insurance_class`: Selection([('motor', 'Motor'), ('fire', 'Fire'), ('marine', 'Marine'), ...])
* `name`: Char (Document title)
* `is_required`: Boolean (default=True)

---

#### E. `insurance.claim.service_provider` (Assessors, Garages & Adjusters - CL-001)
* `claim_id`: Many2one(`insurance.claim`, ondelete='cascade', required=True)
* `partner_id`: Many2one(`res.partner`, string="Service Provider", required=True)
* `provider_type`: Selection([
    ('assessor', 'Motor Assessor'),
    ('adjuster', 'Loss Adjuster'),
    ('garage', 'Repair Garage'),
    ('investigator', 'Private Investigator'),
    ('medical', 'Hospital / Medical Facility'),
    ('lawyer', 'Legal Counsel')
  ], required=True)
* `appointment_date`: Date(default=fields.Date.today)
* `report_received_date`: Date()
* `instructions`: Text()

---

## 4. Key Business Logic Engines

### 4.1. Automated Checklist Population Engine
When a claim is created with a given `policy_id`, the system inspects `policy_id.insurance_class` and auto-populates `insurance.claim.document` checklist items:

```python
# Pseudo-code logic in insurance.claim.create()
templates = self.env['insurance.claim.document.template'].search([
    ('insurance_class', '=', policy.insurance_class)
])
doc_vals = [{
    'claim_id': claim.id,
    'name': t.name,
    'is_required': t.is_required,
} for t in templates]
self.env['insurance.claim.document'].create(doc_vals)
```

**Workflow Guardrail:**
A claim cannot advance from `Document Collection` to `Lodged with Insurer` if:
```python
any(doc.is_required and not doc.is_received for doc in self.document_ids)
```

---

### 4.2. SLA Timer & Working Hours Engine (TM-002 Bridge)
1. Upon stage entry, `stage_entry_date = fields.Datetime.now()`.
2. If `stage_id.sla_hours > 0`, compute `sla_deadline`:
   * Calculates forward using working calendar hours (excluding weekends).
3. A scheduled cron (`ir.cron`) runs hourly:
   * Sets `is_sla_breached = True` for all claims where `stage_id.is_closed == False` and `Datetime.now() > sla_deadline`.
   * Triggers an automated notification/activity to the Claim Handler.

---

### 4.3. Loss-Ratio & Claims Experience Compute Engine (CL-002)

On model `insurance.policy`:
```python
claims_incurred_total = fields.Monetary(
    string="Total Incurred Claims",
    compute="_compute_claims_analytics",
    store=True
)
loss_ratio = fields.Float(
    string="Loss Ratio (%)",
    compute="_compute_claims_analytics",
    store=True,
    digits=(5, 2)
)

@api.depends('claim_ids.settled_amount', 'claim_ids.estimated_amount', 'claim_ids.stage_id.is_closed', 'gross_premium')
def _compute_claims_analytics(self):
    for policy in self:
        # Incurred = Settled amounts for closed claims + Estimated reserve for open claims
        total_incurred = sum(
            c.settled_amount if c.stage_id.is_closed else c.estimated_amount
            for c in policy.claim_ids
        )
        policy.claims_incurred_total = total_incurred
        if policy.gross_premium > 0:
            policy.loss_ratio = (total_incurred / policy.gross_premium) * 100.0
        else:
            policy.loss_ratio = 0.0
```

#### Loss Ratio Status Badge Visualization:
* **`0% - 40%`:** 🟢 **Low / Profitable** (Strong negotiation leverage for client renewal discount)
* **`41% - 69%`:** 🟡 **Moderate / Neutral** (Standard renewal terms)
* **`>= 70%`:** 🔴 **Adverse / Loss Making** (Expect rate hike or higher deductible from insurer)

---

## 5. End-to-End Operational Sequence

```
Client              Broker (Odoo User)            Insurer / Adjuster         Odoo Engine
  │                         │                             │                       │
  │ 1. Incident Call (FNOL) │                             │                       │
  ├────────────────────────>│                             │                       │
  │                         │ 2. Create Claim             │                       │
  │                         ├────────────────────────────────────────────────────>│
  │                         │                             │   3. Auto-load Motor  │
  │                         │                             │      Document Checklist
  │                         │                             │<──────────────────────┤
  │                         │ 4. Request Missing Docs     │                       │
  │<────────────────────────┤    (Email via Chatter)      │                       │
  │ 5. Uploads Abstract     │                             │                       │
  ├────────────────────────>│                             │                       │
  │                         │ 6. Mark Docs "Received"     │                       │
  │                         │ 7. Move to "Lodged"         │                       │
  │                         ├────────────────────────────>│                       │
  │                         │                             │ (Issues Claim Ref #)  │
  │                         │ 8. Record Insurer Ref #     │                       │
  │                         │ 9. Appoint Assessor Provider│                       │
  │                         │                             │ (Assessor Inspects)   │
  │                         │                             │                       │
  │                         │ 10. Receive Report & DV     │                       │
  │                         │<────────────────────────────┤                       │
  │                         │ 11. Move to "DV Review"     │                       │
  │ 12. Signs Discharge     │                             │                       │
  ├────────────────────────>│ 13. Submit Executed DV     │                       │
  │                         ├────────────────────────────>│                       │
  │                         │                             │ (Insurer Releases Pay)│
  │                         │ 14. Mark "Settled"          │                       │
  │                         ├────────────────────────────────────────────────────>│
  │                         │                             │  15. Update Loss Ratio│
  │                         │                             │      on Policy & Client
```

---

## 6. Directory Structure & File Manifest

This can be structured as **`insurance_broker_claims`** (dependent on `insurance_broker_finance`):

```text
insurance_broker_claims/
├── __init__.py
├── __manifest__.py
├── data/
│   ├── ir_sequence_data.xml              # Sequence for Claim Numbers (CLM/YYYY/XXXXX)
│   ├── insurance_claim_stage_data.xml    # Default Pipeline Stages
│   ├── document_template_data.xml        # Default checklists (Motor, Fire, Marine)
│   └── ir_cron_data.xml                  # SLA countdown & breach detector cron
├── security/
│   ├── insurance_claims_security.xml     # Claims user / manager roles & multi-company rules
│   └── ir.model.access.csv               # Permissions matrix
├── models/
│   ├── __init__.py
│   ├── insurance_claim_stage.py          # Stage definition
│   ├── insurance_claim_document.py       # Checklist models & template resolver
│   ├── insurance_claim_service_provider.py # Assessors & Adjusters
│   ├── insurance_claim.py                # Master claim model & calculations
│   └── insurance_policy.py               # Extension: Loss ratio & claims smart-button
├── views/
│   ├── menu_views.xml                    # Claims root menu & submenus
│   ├── insurance_claim_stage_views.xml   # Stage configuration views
│   ├── insurance_claim_views.xml         # Kanban, List, Form views with Document Matrix
│   ├── document_template_views.xml       # Checklist template management
│   └── insurance_policy_views.xml        # Smart buttons for Claims & Loss Ratio gauge
└── tests/
    ├── __init__.py
    ├── test_claim_lifecycle.py           # Test FNOL -> Checklist -> Settlement
    ├── test_sla_breach.py                # Test SLA calculations and deadline flags
    └── test_loss_ratio.py                # Test actuarial formula accuracy
```

---

## 7. Safety, Hygiene & Uninstall Directives

1. **Relation with `insurance.policy`:**
   * `insurance.claim.policy_id` uses `ondelete='restrict'` to prevent accidental deletion of policies with open claims.
   * `insurance.policy` computes claims without storing foreign keys that break on teardown.
2. **Standard Odoo Compatibility:**
   * Service Providers link cleanly to `res.partner` using `ondelete='restrict'`.
   * Checklist attachments reference standard Odoo `ir.attachment` records with `ondelete='set null'`.
3. **Clean Teardown:**
   * If uninstalled, all `insurance_claim_*` tables drop cleanly. No standard Odoo accounting or partner records are modified or destroyed.
```