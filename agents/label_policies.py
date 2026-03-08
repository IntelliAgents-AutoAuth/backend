import json
import os

# Very specific phrases that appear RIGHT BEFORE required documents lists
STRICT_KEYWORDS = [
    "the following documentation is required",
    "documentation required for",
    "required documentation includes",
    "must be submitted",
    "the following must be provided",
    "submit the following",
    "required for prior authorization",
    "authorization requires the following",
    "the following information is required",
    "required clinical information",
    "documentation that must be",
    "the following criteria must be met",
    "required supporting documentation",
    "clinical documentation must include",
    "medical records must include",
    "the following are required",
    "documentation requirements",
    "prior authorization criteria",
    "criteria for approval",
    "approval criteria",
    "coverage criteria",
    "medical necessity criteria",
    "clinical criteria",
    "indication for",
    "indications include",
    "covered when",
    "medically necessary when",
    "authorized when",
    "approved when",
    "eligible when",
    "members may be eligible",
    "covered if",
    "authorized if"
]

CPT_CODES = {
    "75563": "Cardiac MRI with contrast",
    "75561": "Cardiac MRI without contrast",
    "75565": "Cardiac MRI velocity flow mapping",
    "93351": "Echocardiography with stress test",
    "93350": "Echocardiography stress test",
    "78452": "Myocardial perfusion imaging",
    "78451": "Myocardial perfusion imaging single",
    "75571": "CT heart calcium scoring",
    "75572": "CT heart with contrast",
    "75573": "CT heart congenital",
    "75574": "CT angiography heart",
    "33285": "Implantable loop recorder",
    "93653": "Electrophysiology study"
}

BAD_KEYWORDS = [
    "sinusitis", "rhinosinusitis", "colonoscopy",
    "dental", "copyright ©", "table of contents",
    "eustachian", "nasal cavity", "obesity",
    "bariatric", "sleep apnea", "chiropractic",
    "fertility", "infertility", "gender affirmation",
    "cosmetic", "varicose", "knee arthroscopy",
    "hip arthroscopy", "proprietary information of",
    "effective date", "policy number", "page 1 of",
    "page 2 of", "page 3 of"
]

def find_cpt_in_text(text):
    found = []
    for cpt, name in CPT_CODES.items():
        if cpt in text:
            found.append({"cpt_code": cpt, "procedure": name})
    return found

def extract_strict_chunks(text, chunk_size=600):
    chunks = []
    text_lower = text.lower()

    for keyword in STRICT_KEYWORDS:
        start = 0
        while True:
            index = text_lower.find(keyword, start)
            if index == -1:
                break

            # Get chunk starting from keyword
            chunk_start = max(0, index - 50)
            chunk_end = min(len(text), index + chunk_size)
            chunk = text[chunk_start:chunk_end].strip()

            # Check chunk is not bad
            chunk_lower = chunk.lower()
            is_bad = any(bad in chunk_lower for bad in BAD_KEYWORDS)

            # Check chunk has enough useful content
            has_cardiac = any(word in chunk_lower for word in [
                "cardiac", "heart", "imaging", "mri", "ct scan",
                "echocardiogram", "lvef", "ejection fraction",
                "radiology", "authorization", "prior auth",
                "documentation", "diagnosis", "physician",
                "clinical", "procedure", "cpt", "icd"
            ])

            if not is_bad and has_cardiac and len(chunk) >= 150:
                chunks.append(chunk)

            start = index + 1

    return list(set(chunks))

def label_policies(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f:
        policies = json.load(f)

    training_data = []

    for policy in policies:
        text = policy.get("text", "")
        payer = policy.get("payer", "")
        policy_name = policy.get("policy_name", "")
        year = policy.get("year", "")

        if not text:
            print(f"⚠️  Empty: {payer} — {policy_name}")
            continue

        found_cpts = find_cpt_in_text(text)
        chunks = extract_strict_chunks(text)

        for chunk in chunks:
            training_data.append({
                "input": {
                    "payer": payer,
                    "policy_name": policy_name,
                    "year": year,
                    "cpt_codes_found": found_cpts
                },
                "output": {
                    "relevant_text": chunk
                }
            })

        print(f"✅ {payer} — {policy_name} — {len(chunks)} chunks")

    os.makedirs("training-data", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(training_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Done! {len(training_data)} samples")
    print(f"✅ Saved to {output_file}")

    # Show samples
    print("\n--- SAMPLE CHUNKS ---")
    for i, entry in enumerate(training_data[:3]):
        print(f"\nSample {i+1}:")
        print(f"Payer: {entry['input']['payer']}")
        print(f"Policy: {entry['input']['policy_name']}")
        print(f"Text: {entry['output']['relevant_text'][:300]}")
        print("-" * 60)

label_policies(
    "extracted-data/all_policies.json",
    "training-data/labeled_policies.json"
)