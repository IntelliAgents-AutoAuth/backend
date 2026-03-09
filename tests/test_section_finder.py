import json
import os
import torch
from transformers import BertTokenizer, BertForSequenceClassification

# Path to the trained model in agents/
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "agents", "section_finder_model")
MAX_LENGTH = 256

# ─────────────────────────────────────────────
# LOAD MODEL
# ─────────────────────────────────────────────

print("🔄 Loading trained model...")
tokenizer = BertTokenizer.from_pretrained(MODEL_PATH)
model     = BertForSequenceClassification.from_pretrained(MODEL_PATH)
model.eval()
print("✅ Model loaded!\n")


# ─────────────────────────────────────────────
# PREDICT FUNCTION
# ─────────────────────────────────────────────

def predict_section(text: str) -> dict:
    inputs = tokenizer(
        text,
        truncation     = True,
        padding        = "max_length",
        max_length     = MAX_LENGTH,
        return_tensors = "pt"
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs      = torch.softmax(outputs.logits, dim=1)[0]
    pred_id    = torch.argmax(probs).item()
    confidence = round(probs[pred_id].item(), 4)

    label = "REQUIRED_DOC_SECTION" if pred_id == 1 else "NOT_REQUIRED_DOC_SECTION"

    return {
        "label":      label,
        "is_required": pred_id == 1,
        "confidence": confidence,
        "text_preview": text[:80] + "..."
    }


# ─────────────────────────────────────────────
# TEST CASES
# ─────────────────────────────────────────────

test_cases = [

    # ── Should be REQUIRED ──
    {
        "text": "REQUIRED DOCUMENTATION\nThe following documents must be submitted:\n• Clinical notes from treating physician\n• Prior echocardiogram report with LVEF value\n• Letter of medical necessity",
        "expected": "REQUIRED_DOC_SECTION"
    },
    {
        "text": "Documentation Requirements\nProviders must submit all of the following:\n1. Clinical documentation from ordering cardiologist\n2. Echocardiogram report within 12 months\n3. Prior treatment records",
        "expected": "REQUIRED_DOC_SECTION"
    },
    {
        "text": "SUBMISSION REQUIREMENTS\nAll requests must include:\n- Letter of medical necessity\n- Cardiac echo report\n- Six weeks conservative treatment records",
        "expected": "REQUIRED_DOC_SECTION"
    },
    {
        "text": "Supporting Documentation Required\nAetna requires the following for precertification:\n• Completed request form\n• Clinical notes from attending physician\n• Echocardiogram with LVEF documented",
        "expected": "REQUIRED_DOC_SECTION"
    },
    {
        "text": "Clinical documentation supporting medical necessity must be submitted. Providers should include echocardiogram results and prior treatment records.",
        "expected": "REQUIRED_DOC_SECTION"
    },
    {
        "text": "PRIOR AUTHORIZATION CHECKLIST\nEnsure the following documents are included:\n• Clinical notes from treating physician\n• Relevant diagnostic reports\n• Laboratory results\n• Prior treatment failure documentation",
        "expected": "REQUIRED_DOC_SECTION"
    },

    # ── Should be NOT REQUIRED ──
    {
        "text": "POLICY OVERVIEW\nThis policy applies to all United Healthcare commercial members. Prior authorization is required for advanced cardiac imaging procedures.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "CLINICAL CRITERIA\nFor cardiac MRI to be approved LVEF must be documented. Symptoms must be present for minimum 3 months. Prior echocardiogram must be within 12 months.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "AUTOMATIC APPROVAL CONDITIONS\nThe following conditions qualify for automatic approval:\n• LVEF below 40 percent triggers automatic approval\n• Acute myocardial infarction auto approved",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "CONTACT INFORMATION\nFor prior authorization requests contact EviCore at 1-800-397-1630 or visit evicore.com.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "DENIAL CRITERIA\nRequests will be denied when no documented cardiac diagnosis exists or echocardiogram results are conclusive.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "Prior authorization is required for cardiac MRI procedures. Requests must be submitted before the service is rendered.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "SITE OF CARE REQUIREMENTS\nHospital outpatient cardiac MRI requires justification if a freestanding imaging center is available within 30 miles.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
    {
        "text": "STEP THERAPY REQUIREMENTS\nPatients must complete minimum 6 weeks of optimal medical therapy before cardiac MRI will be approved.",
        "expected": "NOT_REQUIRED_DOC_SECTION"
    },
]


# ─────────────────────────────────────────────
# RUN TESTS
# ─────────────────────────────────────────────

print("=" * 60)
print("  SECTION FINDER — TEST RESULTS")
print("=" * 60)

passed = 0
failed = 0

for i, tc in enumerate(test_cases):
    result   = predict_section(tc["text"])
    expected = tc["expected"]
    correct  = result["label"] == expected

    icon = "✅" if correct else "❌"
    tag  = "REQUIRED" if result["is_required"] else "NOT REQUIRED"

    print(f"\n{icon} Test {i+1:02d} — Expected: {expected[:15]}")
    print(f"        Got     : {result['label'][:15]}")
    print(f"        Tag     : {tag}")
    print(f"        Conf    : {result['confidence']}")
    print(f"        Text    : {result['text_preview']}")

    if correct:
        passed += 1
    else:
        failed += 1

print("\n" + "=" * 60)
print("  SUMMARY")
print("=" * 60)
print(f"  Total  : {len(test_cases)}")
print(f"  ✅ Pass : {passed}")
print(f"  ❌ Fail : {failed}")
print(f"  Rate   : {round(passed/len(test_cases)*100, 1)}%")
print("=" * 60)
