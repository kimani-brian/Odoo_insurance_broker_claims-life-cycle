"""Shared constants for the claims module.

Kept in one place so the selection keys, the cover-state whitelist and the
provider types cannot drift between models.
"""

# Line of business, mirroring the values used by insurance_broker_finance so a
# policy class always resolves to a claims checklist preset.
INSURANCE_CLASSES = [
    ("motor", "Motor"),
    ("fire", "Fire & Perils"),
    ("marine", "Marine Cargo"),
    ("health", "Health & Medical"),
    ("life", "Life"),
    ("general", "General/Other"),
]

# Policy states that represent cover actually being in force. A draft policy is
# a quotation and a cancelled one has been terminated, so neither can carry a
# claim.
COVER_STATES = ("bound", "invoiced")

PROVIDER_TYPES = [
    ("assessor", "Motor Assessor"),
    ("adjuster", "Loss Adjuster"),
    ("garage", "Repair Garage"),
    ("investigator", "Private Investigator"),
    ("medical", "Hospital / Medical Facility"),
    ("lawyer", "Legal Counsel"),
    ("other", "Other"),
]
