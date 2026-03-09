import json
import sys
import os
from datetime import datetime

# ── Import your agent ──
# Make sure this path matches your project structure
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── Copy your fetch_policy function here or import it ──
# from agents.policy_fetch_agent import fetch_policy

# ── Test Cases ──
TEST_CASES = [

    # ── BYPASS TESTS ──
    {
        "test_id": "TC-001",
        "test_name": "John Smith - LVEF 35% - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-002",
        "test_name": "LVEF 39% - Just Below Threshold - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Atherosclerotic Heart Disease",
            "icd10": "I25.10",
            "lvef": 39
        }
    },
    {
        "test_id": "TC-003",
        "test_name": "LVEF 20% Severe - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Left Heart Failure",
            "icd10": "I50.1",
            "lvef": 20
        }
    },
    {
        "test_id": "TC-004",
        "test_name": "LVEF 0% Extreme Edge Case - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 0
        }
    },

    # ── NO BYPASS TESTS ──
    {
        "test_id": "TC-005",
        "test_name": "LVEF 40% Boundary - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 40
        }
    },
    {
        "test_id": "TC-006",
        "test_name": "LVEF 55% Normal - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 55
        }
    },
    {
        "test_id": "TC-007",
        "test_name": "LVEF 41% - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 41
        }
    },

    # ── NO LVEF TESTS ──
    {
        "test_id": "TC-008",
        "test_name": "No LVEF Provided - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": None
        }
    },

    # ── DIFFERENT PAYERS ──
    {
        "test_id": "TC-009",
        "test_name": "Aetna - LVEF 35% - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "Aetna",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-010",
        "test_name": "Cigna - LVEF 35% - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "Cigna",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-011",
        "test_name": "Humana - LVEF 35% - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "Humana",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-012",
        "test_name": "Blue Cross Blue Shield - LVEF 35% - BYPASS",
        "expected_result": "BYPASS_TRIGGERED",
        "input": {
            "payer": "Blue Cross Blue Shield",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },

    # ── DIFFERENT CPT CODES ──
    {
        "test_id": "TC-013",
        "test_name": "Lumbar MRI - No LVEF - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "72148",
            "procedure": "MRI Lumbar Spine without contrast",
            "diagnosis": "Low Back Pain",
            "icd10": "M54.5",
            "lvef": None
        }
    },
    {
        "test_id": "TC-014",
        "test_name": "CGM Type 2 Diabetes - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "95251",
            "procedure": "Continuous Glucose Monitor Analysis",
            "diagnosis": "Type 2 Diabetes with Hyperglycemia",
            "icd10": "E11.65",
            "lvef": None
        }
    },
    {
        "test_id": "TC-015",
        "test_name": "Botox Chronic Migraine - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "64615",
            "procedure": "Botulinum Toxin Injection Chronic Migraine",
            "diagnosis": "Chronic Migraine without Aura",
            "icd10": "G43.909",
            "lvef": None
        }
    },
    {
        "test_id": "TC-016",
        "test_name": "Total Knee Replacement - NO BYPASS",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "27447",
            "procedure": "Total Knee Replacement",
            "diagnosis": "Primary Osteoarthritis Right Knee",
            "icd10": "M17.11",
            "lvef": None
        }
    },

    # ── RESPONSE STRUCTURE TESTS ──
    {
        "test_id": "TC-017",
        "test_name": "Response Has Required Documents",
        "expected_result": "HAS_REQUIRED_DOCS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-018",
        "test_name": "Response Has Clinical Criteria",
        "expected_result": "HAS_CLINICAL_CRITERIA",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-019",
        "test_name": "Response Has Confidence Score",
        "expected_result": "HAS_CONFIDENCE",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-020",
        "test_name": "PA Required Always True for Cardiac MRI",
        "expected_result": "PA_REQUIRED_TRUE",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 55
        }
    },

    # ── EDGE CASES ──
    {
        "test_id": "TC-021",
        "test_name": "LVEF Negative Value Edge Case",
        "expected_result": "BYPASS_OR_ERROR",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": -5
        }
    },
    {
        "test_id": "TC-022",
        "test_name": "LVEF 100% Maximum Value",
        "expected_result": "NO_BYPASS",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 100
        }
    },
    {
        "test_id": "TC-023",
        "test_name": "Empty Payer String",
        "expected_result": "RETURNS_RESULT",
        "input": {
            "payer": "",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-024",
        "test_name": "Empty CPT Code",
        "expected_result": "RETURNS_RESULT",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    },
    {
        "test_id": "TC-025",
        "test_name": "Confidence Score Between 0 and 1",
        "expected_result": "CONFIDENCE_VALID",
        "input": {
            "payer": "United Healthcare",
            "cpt_code": "75563",
            "procedure": "Cardiac MRI with contrast",
            "diagnosis": "Dilated Cardiomyopathy",
            "icd10": "I42.0",
            "lvef": 35
        }
    }
]


# ── Test Runner ──
def run_tests(fetch_policy_fn):
    print("\n" + "=" * 70)
    print("  AUTOAUTH POLICY FETCH AGENT — TEST RUNNER")
    print("=" * 70)
    print(f"  Running {len(TEST_CASES)} test cases")
    print(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    passed = 0
    failed = 0
    errors = 0
    results = []

    for tc in TEST_CASES:
        test_id   = tc["test_id"]
        test_name = tc["test_name"]
        expected  = tc["expected_result"]
        inp       = tc["input"]

        try:
            result = fetch_policy_fn(**inp)
            actual_bypass    = result.get("bypass_triggered", False)
            actual_docs      = result.get("required_documents", [])
            actual_criteria  = result.get("clinical_criteria", [])
            actual_pa        = result.get("pa_required", None)
            actual_conf      = result.get("confidence_score", None)
            actual_status    = result.get("status", "unknown")

            # ── Evaluate expected result ──
            test_passed = False
            fail_reason = ""

            if expected == "BYPASS_TRIGGERED":
                test_passed = actual_bypass == True
                fail_reason = f"Expected bypass=True but got bypass={actual_bypass}"

            elif expected == "NO_BYPASS":
                test_passed = actual_bypass == False
                fail_reason = f"Expected bypass=False but got bypass={actual_bypass}"

            elif expected == "HAS_REQUIRED_DOCS":
                test_passed = len(actual_docs) > 0
                fail_reason = f"required_documents is empty"

            elif expected == "HAS_CLINICAL_CRITERIA":
                test_passed = len(actual_criteria) > 0
                fail_reason = f"clinical_criteria is empty"

            elif expected == "HAS_CONFIDENCE":
                test_passed = actual_conf is not None
                fail_reason = f"confidence_score is None"

            elif expected == "PA_REQUIRED_TRUE":
                test_passed = actual_pa == True
                fail_reason = f"Expected pa_required=True but got {actual_pa}"

            elif expected == "CONFIDENCE_VALID":
                test_passed = (
                    actual_conf is not None and
                    0.0 <= actual_conf <= 1.0
                )
                fail_reason = f"confidence_score {actual_conf} not between 0 and 1"

            elif expected in ["BYPASS_OR_ERROR", "RETURNS_RESULT"]:
                test_passed = actual_status in ["success", "error"]
                fail_reason = f"Unexpected status: {actual_status}"

            else:
                test_passed = True

            # ── Print result ──
            status_icon = "✅ PASS" if test_passed else "❌ FAIL"
            bypass_icon = "🚨 BYPASS" if actual_bypass else "📋 NO BYPASS"
            print(f"{status_icon}  [{test_id}]  {test_name}")
            if not test_passed:
                print(f"         ↳ {fail_reason}")
            else:
                print(f"         ↳ {bypass_icon} | Confidence: {actual_conf}")

            if test_passed:
                passed += 1
            else:
                failed += 1

            results.append({
                "test_id":      test_id,
                "test_name":    test_name,
                "expected":     expected,
                "passed":       test_passed,
                "bypass":       actual_bypass,
                "confidence":   actual_conf,
                "fail_reason":  "" if test_passed else fail_reason
            })

        except Exception as e:
            errors += 1
            print(f"💥 ERROR  [{test_id}]  {test_name}")
            print(f"         ↳ Exception: {str(e)}")
            results.append({
                "test_id":    test_id,
                "test_name":  test_name,
                "expected":   expected,
                "passed":     False,
                "error":      str(e)
            })

    # ── Summary ──
    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    print(f"  Total Tests : {len(TEST_CASES)}")
    print(f"  ✅ Passed   : {passed}")
    print(f"  ❌ Failed   : {failed}")
    print(f"  💥 Errors   : {errors}")
    print(f"  Pass Rate   : {round(passed / len(TEST_CASES) * 100, 1)}%")
    print("=" * 70)

    # ── Save results ──
    output = {
        "run_at":     datetime.now().isoformat(),
        "total":      len(TEST_CASES),
        "passed":     passed,
        "failed":     failed,
        "errors":     errors,
        "pass_rate":  f"{round(passed / len(TEST_CASES) * 100, 1)}%",
        "results":    results
    }

    with open("test_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n  Results saved to: test_results.json")
    return output


# ── Entry Point ──
if __name__ == "__main__":

    # ── Import your actual agent ──
    # Option 1: if running from project root
    try:
        from agents.policy_fetch_agent import fetch_policy
        print("✅ Imported fetch_policy from agents.policy_fetch_agent")
    except ImportError:
        # Option 2: paste fetch_policy directly here
        print("⚠️  Could not import — define fetch_policy inline below")

        # ── PASTE YOUR fetch_policy FUNCTION HERE IF IMPORT FAILS ──
        import pickle
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        from datetime import datetime

        MODEL_PATH = "ai_model/autoauth_policy_model.pkl"

        with open(MODEL_PATH, "rb") as f:
            model_data = pickle.load(f)

        vectorizer    = model_data["vectorizer"]
        inputs        = model_data["inputs"]
        outputs       = model_data["outputs"]
        input_vectors = model_data["input_vectors"]

        def parse_output(output_text):
            result = {
                "required_documents": [],
                "clinical_criteria": [],
                "bypass_condition": "None"
            }
            try:
                if "Required Documents:" in output_text:
                    req_part = output_text.split("Required Documents:")[1]
                    req_part = req_part.split("Clinical Criteria:")[0].strip()
                    result["required_documents"] = [
                        doc.strip() for doc in req_part.split(",") if doc.strip()
                    ]
                if "Clinical Criteria:" in output_text:
                    crit_part = output_text.split("Clinical Criteria:")[1]
                    crit_part = crit_part.split("Bypass Condition:")[0].strip()
                    result["clinical_criteria"] = [
                        c.strip() for c in crit_part.split(",") if c.strip()
                    ]
                if "Bypass Condition:" in output_text:
                    bypass_part = output_text.split("Bypass Condition:")[1].strip()
                    result["bypass_condition"] = bypass_part.strip()
            except Exception as e:
                print(f"⚠️ Parse error: {e}")
            return result

        def check_bypass(bypass_condition, lvef=None):
            bypass_triggered = False
            bypass_reason    = None
            if lvef is not None:
                if "40%" in bypass_condition and lvef < 40:
                    bypass_triggered = True
                    bypass_reason    = f"LVEF {lvef}% is below 40% — AUTO APPROVAL triggered"
                elif "35%" in bypass_condition and lvef < 35:
                    bypass_triggered = True
                    bypass_reason    = f"LVEF {lvef}% is below 35% — EXPEDITED REVIEW triggered"
            if "emergency" in bypass_condition.lower():
                bypass_reason = "Emergency cases exempt from PA"
            return bypass_triggered, bypass_reason

        def fetch_policy(payer, cpt_code, procedure, diagnosis, icd10, lvef=None):
            try:
                query        = f"Payer: {payer}. CPT Code: {cpt_code}. Procedure: {procedure}. Diagnosis: {diagnosis}. ICD10: {icd10}."
                query_vector = vectorizer.transform([query])
                similarities = cosine_similarity(query_vector, input_vectors)[0]
                best_idx     = np.argmax(similarities)
                confidence   = round(float(similarities[best_idx]), 4)
                parsed       = parse_output(outputs[best_idx])
                bypass_triggered, bypass_reason = check_bypass(parsed["bypass_condition"], lvef)
                return {
                    "status":           "success",
                    "payer":            payer,
                    "cpt_code":         cpt_code,
                    "procedure":        procedure,
                    "diagnosis":        diagnosis,
                    "icd10_code":       icd10,
                    "pa_required":      True,
                    "confidence_score": confidence,
                    "required_documents": parsed["required_documents"],
                    "clinical_criteria":  parsed["clinical_criteria"],
                    "bypass_condition":   parsed["bypass_condition"],
                    "bypass_triggered":   bypass_triggered,
                    "bypass_reason":      bypass_reason,
                    "fetched_at":         datetime.utcnow().isoformat()
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

    # ── Run all tests ──
    run_tests(fetch_policy)