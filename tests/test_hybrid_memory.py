import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import db.base
from db.session import SessionLocal
from orchestrator.memory import OrchestratorMemory, _MEMORY_CACHE
from crud import crud_case

async def test_hybrid_memory_flow():
    case_id = "PA-20260315-00001"
    db = SessionLocal()
    
    # 1. Clear caches and logs for a clean start
    if case_id in _MEMORY_CACHE:
        del _MEMORY_CACHE[case_id]
    
    print(f"\n--- Testing L1/L2 Memory for {case_id} ---")
    
    # Instance 1: Should be L1 MISS, L2 LOAD
    mem1 = OrchestratorMemory(case_id)
    print("\n[Instance 1] Loading memory (expecting L1 MISS)...")
    mem1.load(db)
    
    # 2. Record a step
    print(f"\n[Instance 1] Recording 'test_step'...")
    mem1.record("test_step", {"input": "val"}, {"output": "ok"}, "SUCCESS")
    
    # 3. Save to sync L1 and L2
    print("\n[Instance 1] Saving to DB...")
    mem1.save(db)
    
    # Instance 2: Should be L1 HIT (no DB query needed)
    print("\n[Instance 2] Loading memory (expecting L1 HIT)...")
    mem2 = OrchestratorMemory(case_id)
    mem2.load(db)
    
    # Verify contents
    history = mem2.get_history()
    print(f"\n[Instance 2] History length: {len(history)}")
    assert any(h.get("step") == "test_step" for h in history), "Step was not found in memory!"
    
    # 4. LangChain Compatibility Check
    print("\n--- LangChain Compatibility Check ---")
    messages = mem2.messages
    print(f"Total LangChain messages: {len(messages)}")
    for i, msg in enumerate(messages):
        print(f"  {i}: {type(msg).__name__} | Step: {msg.additional_kwargs.get('step')}")
    
    assert len(messages) >= 2, "Expected at least 2 messages (Human + AI)"
    assert messages[-2].additional_kwargs["step"] == "test_step"
    
    print("\n--- Hybrid Memory Test Passed! ---")
    db.close()

if __name__ == "__main__":
    import logging
    # Enable info logs to see L1/L2 hits
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_hybrid_memory_flow())
