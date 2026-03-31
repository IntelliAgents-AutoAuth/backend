from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# ─────────────────────────────────────────────────────────────
# SECTION PROMPTS — each section is generated independently
# to keep context clean and output predictable.
# ─────────────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """You are a medical prior authorization specialist writing a formal Cover Letter on behalf of a physician.

Using the patient EHR data below, write a professional cover letter that includes:
- Patient name, date of birth, and insurance member ID
- Requesting physician name, NPI, specialty, and facility
- Date of request (use today's date: {date})
- Procedure requested (CPT code and name)
- A clear, compelling paragraph explaining WHY this procedure is medically necessary for this specific patient

IMPORTANT:
- Write in formal medical letter style
- Be specific — reference actual values from the EHR (LVEF %, BNP levels, diagnosis, etc.)
- Do NOT invent data that is not in the EHR

Take into account these specific POLICY FORMATTING RULES:
{pa_format}

EHR DATA & SUMMARIZED EVIDENCE:
{ehr_data}

Return ONLY the letter text. No preamble, no markdown. Start with "Dear Prior Authorization Review Team,"
"""

CLINICAL_SUMMARY_PROMPT = """You are a clinical documentation specialist. Write a Clinical Summary for a prior authorization request.

Using the EHR data below, write a structured clinical summary that includes:
1. **Diagnosis**: ICD-10 code and full description
2. **Patient History**: Relevant medical background and comorbidities
3. **Reason for Procedure**: Why this specific procedure (CPT code) is needed now
4. **Supporting Evidence**: Specific values from the EHR that support the request (lab results, LVEF, BNP, SOAP notes, prior treatments failed, etc.)
5. **Clinical Justification**: How this procedure meets standard of care guidelines

IMPORTANT:
- Be factual and specific — cite actual EHR values
- Use clear medical terminology
- Keep it under 400 words

Take into account these specific POLICY FORMATTING RULES:
{pa_format}

EHR DATA & SUMMARIZED EVIDENCE:
{ehr_data}

Return ONLY the clinical summary text. Use clear section headers.
"""

CHECKLIST_PROMPT = """You are a prior authorization compliance specialist.

Based on the policy requirements and the patient's EHR data, generate a CHECKLIST of every item the insurance company requires for this authorization.

For each item:
- State the requirement clearly
- State whether it is MET or MISSING based on the EHR data
- Provide the specific evidence/value from the EHR that satisfies it (or explain what is missing)

POLICY RULES & REQUIREMENTS:
{policy_rules}

PATIENT EHR DATA & SUMMARIZED EVIDENCE:
{ehr_data}

Return a JSON array like this (ONLY the JSON, no other text):
[
  {{"item": "LVEF below 35%", "met": true, "evidence": "LVEF = 32% documented on echocardiogram dated 2026-01-15"}},
  {{"item": "Prior medication trial failed", "met": true, "evidence": "Patient trialed beta blockers for 12 weeks with no improvement"}},
  {{"item": "BNP level documented", "met": false, "evidence": "BNP level not present in EHR"}}
]
"""


def get_cover_letter_prompt():
    return ChatPromptTemplate.from_messages([
        ("human", COVER_LETTER_PROMPT)
    ])


def get_clinical_summary_prompt():
    return ChatPromptTemplate.from_messages([
        ("human", CLINICAL_SUMMARY_PROMPT)
    ])


def get_checklist_prompt():
    return ChatPromptTemplate.from_messages([
        ("human", CHECKLIST_PROMPT)
    ])
