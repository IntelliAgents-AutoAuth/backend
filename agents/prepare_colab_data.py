import json

with open("training-data/manual_training_data.json", "r") as f:
    policies = json.load(f)

training_samples = []

for policy in policies:
    payer = policy["input"]["payer"]
    cpt = policy["input"]["cpt_code"]
    procedure = policy["input"]["procedure"]
    diagnosis = policy["input"]["diagnosis"]
    icd10 = policy["input"]["icd10_code"]

    # Required documents as clean string
    req_docs = ", ".join(policy["output"]["required_documents"])

    # Clinical criteria as clean string
    criteria = ", ".join(policy["output"]["clinical_criteria"])

    # Bypass condition
    bypass = policy["output"]["bypass_condition"]

    # ── Input text (what model receives) ──
    input_text = f"Payer: {payer}. CPT Code: {cpt}. Procedure: {procedure}. Diagnosis: {diagnosis}. ICD10: {icd10}."

    # ── Output text (what model should return) ──
    output_text = f"Required Documents: {req_docs}. Clinical Criteria: {criteria}. Bypass Condition: {bypass}."

    training_samples.append({
        "input": input_text,
        "output": output_text,
        "payer": payer,
        "cpt_code": cpt
    })

with open("training-data/colab_training_data.json", "w") as f:
    json.dump(training_samples, f, indent=2)

print(f"✅ {len(training_samples)} samples ready for Colab!")
print()
print("=== SAMPLE PREVIEW ===")
print(f"INPUT:  {training_samples[0]['input']}")
print()
print(f"OUTPUT: {training_samples[0]['output'][:300]}")