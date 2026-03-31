"""
Test: Orchestrator Memory Verification
=======================================
This test checks that the OrchestratorMemory correctly:
  1. Records which agents were called
  2. Stores inputs and results per step
  3. Persists to DB (audit_log column)
  4. Correctly answers already_ran / succeeded / get_last_result queries

Run from backend/ directory:
    python tests/test_orchestrator_memory.py
"""

import os
import sys

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from db.session import SessionLocal
from crud import crud_case
from orchestrator.memory import OrchestratorMemory


def test_memory_record_and_query():
    """Test in-memory: record steps and query them."""
    print("\n--- Test: In-Memory Record + Query ---")
    mem = OrchestratorMemory("TEST-CASE-001")

    # Should have no history
    assert not mem.already_ran("gap_analysis"), "Expected: gap_analysis not yet run"
    assert not mem.succeeded("gap_analysis"),   "Expected: gap_analysis not succeeded"
    assert mem.get_last_result("gap_analysis") is None

    # Record a successful gap_analysis
    mem.record(
        step="gap_analysis",
        inputs={"case_id": "TEST-CASE-001", "pdf_path": "/some/path.pdf"},
        result={"event": "GAP_CLEARED", "output": {"status": "GAP_CLEARED", "missing_documents": []}},
        status="SUCCESS",
    )

    assert mem.already_ran("gap_analysis"),     "Expected: gap_analysis already ran"
    assert mem.succeeded("gap_analysis"),       "Expected: gap_analysis succeeded"
    result = mem.get_last_result("gap_analysis")
    assert result is not None,                   "Expected: result is not None"
    assert result["event"] == "GAP_CLEARED",    f"Expected GAP_CLEARED, got {result['event']}"

    # Record a failed eligibility step
    mem.record(
        step="eligibility",
        inputs={"case_id": "TEST-CASE-001"},
        result={"event": "FAILED", "error": "API error"},
        status="FAILED",
    )

    assert mem.already_ran("eligibility"),      "Expected: eligibility ran"
    assert not mem.succeeded("eligibility"),    "Expected: eligibility did NOT succeed"

    print(f"  History: {mem.summary()}")
    print("  PASSED ✅")


def test_memory_persist_and_load(case_id: str):
    """Test DB persistence: save then reload from audit_log column."""
    print(f"\n--- Test: Persist + Load for case {case_id} ---")
    db = SessionLocal()

    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if not db_case:
            print(f"  Case '{case_id}' not found in DB. Skipping persist test.")
            return

        mem = OrchestratorMemory(case_id)
        mem.load(db)
        initial_count = len(mem.get_history())
        print(f"  Loaded {initial_count} existing entries.")

        # Record a test step
        mem.record(
            step="ehr_fetch",
            inputs={"case_id": case_id},
            result={"event": "EHR_FETCH_DONE"},
            status="SUCCESS",
        )
        mem.save(db)
        print(f"  Saved 1 new entry.")

        # Reload fresh
        mem2 = OrchestratorMemory(case_id)
        mem2.load(db)

        assert len(mem2.get_history()) >= initial_count + 1, "Memory not persisted correctly"
        assert mem2.already_ran("ehr_fetch"), "ehr_fetch should be in loaded memory"

        print(f"  Total entries after save+load: {len(mem2.get_history())}")
        print(f"  History: {mem2.summary()}")
        print("  PASSED ✅")

    finally:
        db.close()


def test_transition_table():
    """Test the orchestrator's transition table resolution."""
    print("\n--- Test: Transition Table ---")
    from orchestrator.case_orchestrator import CaseOrchestrator, TRANSITIONS

    orch = CaseOrchestrator("DUMMY")

    test_cases = [
        ("CASE_CREATED",    None,                   "ehr_fetch"),
        ("EHR_FETCH_DONE",  "EHR_FETCHED",          "gap_analysis"),
        ("GAP_CLEARED",     "GAP_CLEARED",          "eligibility"),
        ("DOCUMENTS_UPLOADED", "GAP_CLEARED",       "eligibility"),
        ("ELIGIBLE",        "APPROVED",             "packet_gen"),
        ("PACKET_DONE",     "PACKET_READY",         "pending_approval"),
        ("STAFF_APPROVED",  "PENDING_APPROVAL",     "submit"),
        ("GAP_FOUND",       "GAP_FOUND",            None),   # no transition — wait for docs
        ("NOT_ELIGIBLE",    "DENIED",               None),   # terminal
    ]

    for event, status, expected in test_cases:
        got = orch._resolve_next_step(event, status)
        status_str = f"status={status}" if status else "status=*"
        ok = "✅" if got == expected else "❌"
        print(f"  {ok}  ({event}, {status_str}) → {got!r}  (expected {expected!r})")
        assert got == expected, f"MISMATCH: got {got!r}, expected {expected!r}"

    print("  All transitions correct ✅")


if __name__ == "__main__":
    print("=" * 60)
    print("Orchestrator Memory Verification Tests")
    print("=" * 60)

    test_memory_record_and_query()
    test_transition_table()

    # Update this case_id to one that exists in your local DB
    REAL_CASE_ID = "PA-20260309-00002"
    test_memory_persist_and_load(REAL_CASE_ID)

    print("\n" + "=" * 60)
    print("All tests completed.")
    print("=" * 60)
