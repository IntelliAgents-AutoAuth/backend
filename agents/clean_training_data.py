import json
import os

# These words MUST appear in a good chunk
GOOD_KEYWORDS = [
    "required",
    "must submit",
    "clinical notes",
    "documentation",
    "prior authorization",
    "medical necessity",
    "must include",
    "criteria",
    "must be present",
    "diagnosis",
    "physician",
    "echocardiogram",
    "lvef",
    "ejection fraction",
    "imaging",
    "cardiac",
    "heart",
    "cpt",
    "icd",
    "procedure",
    "authorization",
    "precertification",
    "submission",
    "submit",
    "approval",
    "coverage"
]

# These words mean chunk is BAD — remove it
BAD_KEYWORDS = [
    "sinusitis",
    "rhinosinusitis",
    "colonoscopy",
    "dental",
    "orthodontic",
    "copyright",
    "proprietary information",
    "table of contents",
    "eustachian",
    "nasal cavity",
    "paranasal",
    "obesity",
    "bariatric",
    "sleep apnea",
    "chiropractic",
    "fertility",
    "infertility",
    "gender affirmation",
    "hair removal",
    "cosmetic",
    "varicose",
    "knee arthroscopy",
    "hip arthroscopy"
]

def is_good_chunk(chunk):
    chunk_lower = chunk.lower()

    # Check for bad keywords first
    for bad in BAD_KEYWORDS:
        if bad in chunk_lower:
            return False

    # Must have at least 2 good keywords
    good_count = 0
    for good in GOOD_KEYWORDS:
        if good in chunk_lower:
            good_count += 1

    return good_count >= 2

def is_good_length(chunk):
    # Must be between 100 and 1000 characters
    return 100 <= len(chunk) <= 1000

def clean_data(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f:
        training_data = json.load(f)

    print(f"Total samples before cleaning: {len(training_data)}")

    cleaned_data = []
    removed_count = 0

    for entry in training_data:
        chunk = entry["output"]["relevant_text"]

        if is_good_chunk(chunk) and is_good_length(chunk):
            cleaned_data.append(entry)
        else:
            removed_count += 1

    print(f"Removed: {removed_count} bad samples")
    print(f"Kept: {len(cleaned_data)} good samples")

    # Save cleaned data
    os.makedirs("training-data", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Cleaning complete!")
    print(f"✅ Saved to {output_file}")

    # Show sample of kept chunks
    print("\n--- SAMPLE OF KEPT CHUNKS ---")
    for i, entry in enumerate(cleaned_data[:3]):
        print(f"\nSample {i+1}:")
        print(f"Payer: {entry['input']['payer']}")
        print(f"Policy: {entry['input']['policy_name']}")
        print(f"Text preview: {entry['output']['relevant_text'][:200]}")
        print("-" * 50)

# Run
clean_data(
    "training-data/labeled_policies.json",
    "training-data/cleaned_policies.json"
)