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
        # PT-002 — COMPLETE
        # All fields present
        # Agent should proceed without asking anything
        "patient_id":          "PT-002",
        "patient_first_name":  "Jane",
        "patient_last_name":   "Smith",
        "date_of_birth":       "1972-11-03",
        "gender":              "Female",
        "insurance_company":   "United Healthcare",
        "member_id":           "UHC-991234",
        "policy_number":       "UHC-POL-2026-002",
        "group_number":        "GRP-7721",
        "plan_name":           "UHC Gold Plus",
        "icd10_code":          "E11.65",
        "diagnosis":           "Type 2 Diabetes with Hyperglycemia",
        "cpt_code":            "95251",
        "procedure_name":      "Continuous Glucose Monitoring System",
        "physician_name":      "Dr. Priya Nair",
        "physician_npi":       "9876543210",
        "physician_specialty": "Endocrinology",
        "facility_name":       "Metro Diabetes Clinic",
        "lab_results": {
            "HbA1c":           {"value": "8.2",  "unit": "%"},
            "Fasting Glucose": {"value": "180",  "unit": "mg/dL"}
        },
        "created_at":          datetime.datetime(2026, 3, 1, 9, 0, 0),
        "updated_at":          datetime.datetime(2026, 3, 1, 9, 0, 0)
    },

    # ─────────────────────────────────────────
    # INCOMPLETE RECORDS — Gaps present
    # Agent must detect and request upload
    # ─────────────────────────────────────────

    {
        # PT-003 — MISSING lab results
        # Agent must ask to upload lab report
        "patient_id":          "PT-003",
        "patient_first_name":  "Alice",
        "patient_last_name":   "Johnson",
        "date_of_birth":       "1960-03-25",
        "gender":              "Female",
        "insurance_company":   "Cigna",
        "member_id":           "CIG-100234",
        "policy_number":       "CIG-POL-2026-003",
        "group_number":        "GRP-3310",
        "plan_name":           "Cigna Open Access Plus",
        "icd10_code":          "I25.10",
        "diagnosis":           "Atherosclerotic heart disease",
        "cpt_code":            "33533",
        "procedure_name":      "Coronary Artery Bypass Graft x3",
        "physician_name":      "Dr. Ramesh Kumar",
        "physician_npi":       "1234567890",
        "physician_specialty": "Cardiothoracic Surgery",
        "facility_name":       "Heart Care Institute",
        "lab_results":         {},
        # MISSING — agent must detect and request
        # lab_results → empty
        "created_at":          datetime.datetime(2026, 3, 1, 9, 0, 0),
        "updated_at":          datetime.datetime(2026, 3, 1, 9, 0, 0)
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
