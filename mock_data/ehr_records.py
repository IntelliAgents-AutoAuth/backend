import datetime

MOCK_EHR_RECORDS = [

    # ─────────────────────────────────────────
    # COMPLETE RECORDS — No gaps
    # Agent proceeds automatically
    # ─────────────────────────────────────────

    {
        # PT-001 — COMPLETE
        # All fields present
        # Agent should proceed without asking anything
        "patient_id":          "PT-001",
        "patient_first_name":  "John",
        "patient_last_name":   "Smith",
        "date_of_birth":       "1968-03-15",
        "gender":              "Male",
        "insurance_company":   "United Healthcare",
        "member_id":           "UHC-887612",
        "policy_number":       "UHC-POL-2026-001",
        "group_number":        "GRP-7721",
        "plan_name":           "UHC Gold Plus",
        "icd10_code":          "I42.0",
        "diagnosis":           "Dilated Cardiomyopathy",
        "cpt_code":            "75563",
        "procedure_name":      "Cardiac MRI with contrast",
        "physician_name":      "Dr. Ramesh Kumar",
        "physician_npi":       "1234567890",
        "physician_specialty": "Cardiology",
        "facility_name":       "City Heart Institute",
        "lab_results": {
            "BNP":             {"value": "450",    "unit": "pg/mL"},
            "metabolic_panel": {"value": "Normal", "unit": None}
        },
        "created_at":          datetime.datetime(2026, 3, 1, 9, 0, 0),
        "updated_at":          datetime.datetime(2026, 3, 1, 9, 0, 0)
    },
{
    # PT-002 — FULLY COMPLETE
    # All fields present including uploaded docs
    # Gap Analysis should find ZERO missing items
    # Agent proceeds directly to Eligibility ✅

    "patient_id":          "PT-002",
    "patient_first_name":  "Jane",
    "patient_last_name":   "Smith",
    "date_of_birth":       "1972-11-03",
    "gender":              "Female",

    # ── Insurance ──────────────────────────
    "insurance_company":   "United Healthcare",
    "member_id":           "UHC-991234",
    "policy_number":       "UHC-POL-2026-002",
    "group_number":        "GRP-7721",
    "plan_name":           "UHC Gold Plus",

    # ── Clinical ───────────────────────────
    "icd10_code":          "E11.65",
    "diagnosis":           "Type 2 Diabetes with Hyperglycemia",
    "cpt_code":            "95251",
    "procedure_name":      "Continuous Glucose Monitoring System",

    # ── Physician ──────────────────────────
    "physician_name":      "Dr. Priya Nair",
    "physician_npi":       "9876543210",
    "physician_specialty": "Endocrinology",
    "facility_name":       "Metro Diabetes Clinic",

    # ── Lab Results ────────────────────────
    # Policy asks for HbA1c + Fasting Glucose
    # Both present and above threshold ✅
    "lab_results": {
        "HbA1c": {
            "value": "8.2",
            "unit":  "%",
            "date":  "2026-02-15",
            "lab":   "Metro Diabetes Clinic Lab",
            "reference_range": "Normal below 7.0%",
            "flag":  "HIGH"
        },
        "Fasting_Glucose": {
            "value": "180",
            "unit":  "mg/dL",
            "date":  "2026-02-28",
            "lab":   "Metro Diabetes Clinic Lab",
            "reference_range": "Normal 70-99 mg/dL",
            "flag":  "HIGH"
        }
    },

    # ── Clinical Justification ─────────────
    # Policy asks for clinical justification note
    # Provided as text so agent finds it ✅
    "clinical_justification": {
        "note": """Patient Jane Smith presents with 
                   Type 2 Diabetes Mellitus with 
                   Hyperglycemia (E11.65). HbA1c of 
                   8.2% despite 12 months of oral 
                   medication therapy. Fasting glucose 
                   consistently above 150 mg/dL. 
                   Standard fingerstick monitoring 
                   insufficient to manage glucose 
                   variability. CGM medically necessary 
                   for real-time glucose management 
                   and hypoglycemia prevention.""",
        "physician": "Dr. Priya Nair",
        "npi":       "9876543210",
        "specialty": "Endocrinology",
        "date":      "2026-03-01",
        "signed":    True
    },

    # ── Physician Order ────────────────────
    # Policy asks for physician order letter
    # Provided as structured data ✅
    "physician_order": {
        "procedure":    "Continuous Glucose Monitoring System",
        "cpt_code":     "95251",
        "icd10_code":   "E11.65",
        "physician":    "Dr. Priya Nair",
        "npi":          "9876543210",
        "facility":     "Metro Diabetes Clinic",
        "date":         "2026-03-01",
        "signed":       True,
        "letterhead":   True
    },

    # ── Prior Treatment Records ────────────
    # Shows 12 months of medication history ✅
    "prior_treatment_records": [
        {
            "medication":  "Metformin",
            "dose":        "1000mg",
            "frequency":   "twice daily",
            "start_date":  "2025-01-01",
            "end_date":    "ongoing",
            "duration":    "15 months",
            "response":    "Partial — HbA1c improved from 9.5% to 8.2% but glucose variability persists",
            "status":      "CURRENT"
        },
        {
            "medication":  "Glipizide",
            "dose":        "5mg",
            "frequency":   "once daily",
            "start_date":  "2025-03-01",
            "end_date":    "2025-09-01",
            "duration":    "6 months",
            "response":    "Discontinued — hypoglycemic episodes reported",
            "status":      "DISCONTINUED"
        }
    ],

    "created_at": datetime.datetime(2026, 3, 1, 9, 0, 0),
    "updated_at": datetime.datetime(2026, 3, 1, 9, 0, 0)
},

    {
        # PT-004 — MISSING physician specialty + insurance details
        # Agent must ask to upload referral letter
        "patient_id":          "PT-004",
        "patient_first_name":  "Bob",
        "patient_last_name":   "Williams",
        "date_of_birth":       "1990-09-17",
        "gender":              "Male",
        "insurance_company":   "Blue Cross Blue Shield",
        "member_id":           None,
        "policy_number":       None,
        "group_number":        None,
        "plan_name":           "BCBS PPO Standard",
        "icd10_code":          "M54.5",
        "diagnosis":           "Low back pain",
        "cpt_code":            "72148",
        "procedure_name":      "MRI Lumbar Spine without contrast",
        "physician_name":      "Dr. Suresh Patel",
        "physician_npi":       "1122334455",
        "physician_specialty": None,
        "facility_name":       "Advanced Imaging Center",
        "lab_results":         {},
        # MISSING — agent must detect and request
        # member_id          → None
        # policy_number      → None
        # group_number       → None
        # physician_specialty → None
        # lab_results        → empty
        "created_at":          datetime.datetime(2026, 3, 1, 9, 0, 0),
        "updated_at":          datetime.datetime(2026, 3, 1, 9, 0, 0)
    },

    {
        # PT-005 — MISSING diagnosis + lab results
        # Agent must ask to upload clinical note + lab report
        "patient_id":          "PT-005",
        "patient_first_name":  "Maria",
        "patient_last_name":   "Garcia",
        "date_of_birth":       "1978-12-30",
        "gender":              "Female",
        "insurance_company":   "Humana",
        "member_id":           "HUM-H12345",
        "policy_number":       "HUM-POL-2026-005",
        "group_number":        "GRP-4450",
        "plan_name":           "Humana Gold Plus",
        "icd10_code":          None,
        "diagnosis":           None,
        "cpt_code":            "64615",
        "procedure_name":      "Botox Injection for Chronic Migraine",
        "physician_name":      "Dr. Anita Sharma",
        "physician_npi":       "5566778899",
        "physician_specialty": "Neurology",
        "facility_name":       "Neuroscience Associates",
        "lab_results":         {},
        # MISSING — agent must detect and request
        # icd10_code  → None
        # diagnosis   → None
        # lab_results → empty
        "created_at":          datetime.datetime(2026, 3, 1, 9, 0, 0),
        "updated_at":          datetime.datetime(2026, 3, 1, 9, 0, 0)
    }
]
