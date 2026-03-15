"""
Eligibility Checker Tool

Formats an EHR record dict into a clean, structured summary string that the
eligibility agent's LLM can reason over when comparing against a policy PDF.
"""

import json
from langchain_core.tools import tool


def format_ehr_for_eligibility(ehr_data: dict) -> str:
    """
    Formats an EHR record into a human-readable summary for LLM reasoning.

    Args:
        ehr_data: The EHR record dict returned by ehr_fetcher / extracted_data table.

    Returns:
        A structured multi-line string summarising the patient's clinical profile.
    """
    if not ehr_data:
        return "ERROR: No EHR data provided or found for this patient."

    # Safely pull fields with fallbacks
    def get(key, default="N/A"):
        return ehr_data.get(key) or default

    lines = [
        "=== PATIENT EHR SUMMARY ===",
        f"Patient ID     : {get('patient_id')}",
        f"Name           : {get('patient_first_name')} {get('patient_last_name')}",
        f"Date of Birth  : {get('patient_dob', get('date_of_birth'))}",
        f"Gender         : {get('patient_gender', get('gender'))}",
        "",
        "=== INSURANCE ===",
        f"Insurance      : {get('payer_name', get('insurance_company'))}",
        f"Member ID      : {get('member_id')}",
        f"Policy Number  : {get('policy_number')}",
        f"Group Number   : {get('group_number')}",
        f"Plan Name      : {get('plan_name')}",
        "",
        "=== CLINICAL ===",
        f"Diagnosis (ICD-10) : {get('primary_icd10_code', get('icd10_code'))} — {get('primary_diagnosis', get('diagnosis'))}",
        f"Procedure (CPT)    : {get('cpt_code')} — {get('procedure_name', 'N/A')}",
        f"Physician          : {get('physician_name')} (NPI: {get('physician_npi')})",
        f"Specialty          : {get('physician_specialty')}",
        f"Facility           : {get('facility_name')}",
        "",
        "=== LAB RESULTS ===",
    ]

    lab_results = ehr_data.get("lab_results") or {}
    if lab_results:
        for key, val in lab_results.items():
            lines.append(f"  {key}: {val}")
    else:
        lines.append("  No lab results available.")

    # Key numeric markers
    for field, label in [
        ("lvef_percent", "LVEF"),
        ("lvef_from_echo", "LVEF (Echo)"),
        ("bnp_level", "BNP Level"),
    ]:
        val = ehr_data.get(field)
        if val is not None:
            lines.append(f"  {label}: {val}")

    lines += [
        "",
        "=== CLINICAL NOTES ===",
        f"Subjective  : {get('soap_subjective')}",
        f"Objective   : {get('soap_objective')}",
        f"Assessment  : {get('soap_assessment')}",
        f"Plan        : {get('soap_plan')}",
        f"Justification: {get('clinical_justification')}",
        "",
        "=== PRIOR AUTH MARKERS ===",
        f"Prior Treatment Failed : {get('treatment_failed')}",
        f"Treatment Duration     : {get('treatment_duration_weeks')} weeks",
        f"LVEF Below 40%         : {get('lvef_below_40')}",
        f"Bypass Condition Met   : {get('bypass_condition_met')}",
        f"Bypass Reason          : {get('bypass_reason')}",
        f"Auto-Approval Triggered: {get('auto_approval_triggered')}",
    ]

    return "\n".join(lines)


# Tool for use in LangChain agents
eligibility_checker = tool(format_ehr_for_eligibility)
