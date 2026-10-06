Here is how an insurance broker actually manages claims in practice, followed by how we translate that into an elegant, scalable workflow in **Odoo**.

---

# Part 1: The End-to-End Broker Claim Workflow

As a broker, **Transnep does not pay claims directly**. The broker acts as an **advocate and project manager** for the client, chasing the underwriter, adjusters, and service providers to ensure fast, fair settlement.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               BROKER CLAIM LIFECYCLE                                   │
└────────────────────────────────────────────────────────────────────────────────────────┘

  [1. FNOL Intake]          [2. Document Checklist]         [3. Lodging with Insurer]
  Client calls/emails       Broker checks policy active,    Broker files formal notice,
  loss details & date       assigns missing doc list        receives Insurer Claim #
         │                           │                                │
         ▼                           ▼                                ▼
  [6. Claim Settlement]     [5. Offer & Discharge (DV)]     [4. Assessment & Follow-up]
  Payment confirmed,        Insurer issues offer/DV,        Assessor/Investigator visits,
  loss ratio updated        client signs, broker submits    broker chases assessment SLA
```

### Stage-by-Stage Breakdown

| Stage | What Happens in the Real World | Key Actors |
| :--- | :--- | :--- |
| **1. First Notification of Loss (FNOL)** | The client alerts the broker: *"Our truck had an accident on Mombasa Road"* or *"A warehouse roof leaked"*. Broker logs: date of loss, location, estimated damage, driver/staff involved. | Client ➔ Broker |
| **2. Policy Verification & Document Check** | Broker checks whether the policy is active and premium is paid. Broker issues a tailored checklist to the client (e.g., police abstract, driver's license, photos, repair estimates). | Broker ➔ Client |
| **3. Lodged with Insurer** | Once initial documents are ready, the broker formally submits the claim to the insurance company and obtains the **Insurer Claim Reference Number**. | Broker ➔ Insurer |
| **4. Assessment & Adjuster Follow-up** | The insurer appoints an independent assessor or loss adjuster. The broker tracks SLAs: Did the assessor inspect the damage within 48 hours? Has the assessment report been submitted? | Insurer, Assessor, Broker |
| **5. Offer & Discharge Voucher (DV)** | Insurer makes an offer or issues a **Discharge Voucher (DV)** for the agreed amount (less policy excess/deductibles). Broker reviews it for fairness, gets client signature, and submits it back. | Insurer ➔ Broker ➔ Client |
| **6. Settlement & Closure** | Insurer releases payment (either directly to the client, or direct to the repair garage/hospital). The broker logs the final settled amount, marks claim closed, and recalculates the client's **Loss Ratio**. | Insurer ➔ Client / Broker |

---

# Part 2: How We Design This in Odoo

Odoo’s framework is naturally built for case management. We can build this using a visual **Kanban Pipeline** powered by automated tracking, SLA clocks, and chatter.

---

### 1. The Core Odoo Model: `insurance.claim`

```
                                  insurance.policy
                                         │ 1
                                         │
                                         │ *
                                  insurance.claim
                 ┌───────────────────────┼───────────────────────┐
                 │ 1                     │ 1                     │ 1
                 │ *                     │ *                     │ *
     insurance.claim.document   insurance.claim.milestone   mail.thread / activity
    (Checklist & attachments)   (SLA clocks & turnaround)   (Emails, calls, audits)
```

#### Key Fields on `insurance.claim`:
* **Identification:** `name` (e.g., `CLM/2026/00042`), `insurer_claim_ref` (the underwriter's reference number).
* **Links:** `policy_id` (Many2one), `client_id` (related), `underwriter_id` (related).
* **Incident Data:** `date_of_loss`, `date_notified` (FNOL date), `loss_description`, `incident_location`.
* **Financials:** 
  * `estimated_claim_amount` (initial estimate)
  * `assessed_amount` (from adjuster report)
  * `excess_deductible` (client's policy excess)
  * `final_settlement_amount` (net amount approved by insurer)
* **Status Pipeline (`stage_id`):**
  * `1. FNOL / Intake`
  * `2. Awaiting Documents`
  * `3. Lodged with Insurer`
  * `4. Under Assessment`
  * `5. Discharge Voucher (DV) Issued`
  * `6. Settled / Paid`
  * `7. Repudiated / Rejected`

---

### 2. Document Checklist Engine (`insurance.claim.document`)
*Requirement CL-001 calls for "document requirements and SLA status."*

Instead of leaving documents scattered in emails:
* When a claim is created for a **Motor Policy**, the system automatically populates a document checklist:
  * [ ] Police Abstract Form
  * [ ] Driver's License Copy
  * [ ] Vehicle Logbook Copy
  * [ ] Detailed Repair Estimate / Pro-forma
  * [ ] Scene Photos
* When the client sends a document, the broker uploads it directly against the line item and marks it **Received**.
* The claim cannot advance to *"Lodged with Insurer"* until all mandatory documents are marked **Received**.

---

### 3. Timeline, SLA & Activity Tracking (Satisfies TM-001, TM-002 & CL-001)
Brokers win client trust by keeping claims moving. Odoo handles this with:

1. **SLA Timers & Escalations:**
   * **Target 1:** File FNOL with insurer within **24 hours** of client report.
   * **Target 2:** Insurer appoints assessor within **48 hours**.
   * **Target 3:** Insurer issues DV within **14 days** of assessment report.
   * If an SLA timer breaches, the card turns **Red** on the Kanban board and schedules an urgent Odoo activity for the account manager to chase the insurer.
2. **Centralized Email Chatter:**
   * All emails sent to the insurer (e.g., `SafeGuard Claims Desk`) and client happen directly from the Odoo claim screen. Incoming replies are routed straight into the claim thread.

---

### 4. Loss Ratio & Renewal Analytics (Requirement CL-002)
*Loss Ratio = (Total Incurred Claims ÷ Total Earned Premium) × 100%*

When a client’s policy comes up for annual renewal, the broker needs to know:
* How many claims did Apex Logistics submit this year?
* How much did the underwriter pay out?
* What is the Loss Ratio?

In Odoo, we add a computed statistical block or smart button on `insurance.policy` and `res.partner`:
* **Total Premium Paid:** $10,000
* **Total Claims Paid:** $3,500
* **Loss Ratio:** **35%** (Healthy policy — broker can negotiate premium discounts at renewal).
* **If Loss Ratio is > 70%:** Broker is warned that the underwriter will likely demand higher premiums or higher deductibles.

---

# Part 3: A Concrete Example of the User Journey

1. **Monday 9:00 AM:** *Apex Logistics* calls: truck involved in a minor collision.
2. **Monday 9:15 AM:** Broker clicks **New Claim** in Odoo, selects Apex's active fleet policy. 
   * System auto-assigns the required motor claim checklist.
   * Status: **FNOL / Intake**.
3. **Tuesday 11:00 AM:** Client emails police abstract and photos. Broker drags-and-drops them into the checklist lines.
4. **Tuesday 2:00 PM:** Broker clicks **Submit to Insurer**. Odoo sends an automated claim packet to SafeGuard Insurance with all attachments. Status: **Lodged with Insurer**.
5. **Thursday:** SafeGuard replies with claim number `CLM-SG-9981`. Broker enters this into Odoo. 
6. **Next Week:** Assessor submits report approving `$2,800`. SafeGuard sends a Discharge Voucher (DV) for `$2,500` (after $300 excess).
7. **Settlement:** Apex signs DV, SafeGuard pays the repair garage. Broker clicks **Mark Settled**, records `$2,500`.
8. **Result:** The claim is archived, the client gets a notification, and Apex Logistics' loss ratio updates automatically on their partner dashboard.

---

