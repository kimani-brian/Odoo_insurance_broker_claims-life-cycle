{
    "name": "Insurance Broker Claims",
    "version": "19.0.2.0.0",
    "category": "Accounting/Insurance",
    "summary": "Claims case management: FNOL intake, document checklist gating, SLA clocks and loss ratio analytics.",
    "description": """
Insurance Broker Claims (Transnep RFP 3.7)
===========================================
* FNOL intake and policy-linked claim case files
* Line-of-business document checklists that hard-gate lodging with the insurer
* Configurable Kanban stages with SLA clocks and automatic breach detection
* Earned-premium pro-rated loss ratio per policy and per client
* Zero-residue uninstall: all FKs onto core models use ondelete='set null'

Claims link to the policy book owned by the 'insurance_broker_finance' module.
There is no second copy of the policy: the loss ratio is computed directly on
insurance.policy, so the finance module is a required dependency.
    """,
    "author": "Transnep Insurance Brokers Limited",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "insurance_broker_finance",
    ],
    "data": [
        "security/insurance_claims_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/insurance_claim_stage_data.xml",
        "data/insurance_claim_document_template_data.xml",
        "data/ir_cron_data.xml",
        "views/insurance_claim_stage_views.xml",
        "views/insurance_claim_document_template_views.xml",
        "views/insurance_claim_document_views.xml",
        "views/insurance_claim_service_provider_views.xml",
        "views/insurance_claim_views.xml",
        "views/insurance_policy_views.xml",
        "views/res_partner_views.xml",
        # menus load last: every parent and action above must already exist
        "views/menu_views.xml",
    ],
    "demo": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
