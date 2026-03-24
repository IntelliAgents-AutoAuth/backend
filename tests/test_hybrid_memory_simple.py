import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from orchestrator.memory import OrchestratorMemory, _MEMORY_CACHE

# Setup logging
logging.basicConfig(level=logging.INFO)

async def test_simple_cache():
    case_id = "TEST-HYBRID-001"
    
    # 1. Start with clean cache
    if case_id in _MEMORY_CACHE:
        del _MEMORY_CACHE[case_id]
        
    print("\n--- [Simple Test] Step 1: Record in RAM ---")
    mem = OrchestratorMemory(case_id)
    mem.record("test_step_1", {"foo": "bar"}, {"status": "ok"})
    
    assert case_id in _MEMORY_CACHE, "Case should be in L1 Cache after record()"
    assert len(_MEMORY_CACHE[case_id]) == 1
    
    print("\n--- [Simple Test] Step 2: L1 Cache Hit ---")
    # Fresh instance, but same case_id
    mem2 = OrchestratorMemory(case_id)
    # Mocking DB so it doesn't fail on connection
    class MockDB: 
        def add(self, x): pass
        def commit(self): pass
        def refresh(self, x): pass
        def close(self): pass
    
    # load() should HIT L1 and NOT try to query DB if it's already there
    # But wait, our current load() logic is:
    # if self.case_id in _MEMORY_CACHE: self._log = _MEMORY_CACHE[self.case_id]; return
    mem2.load(MockDB()) 
    
    assert len(mem2.get_history()) == 1, "Should have loaded from L1 Cache"
    assert mem2.get_history()[0]["step"] == "test_step_1"
    
    print("\n--- [Simple Test] Step 3: LangChain Messages ---")
    msgs = mem2.messages
    assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"
    assert msgs[0].additional_kwargs["step"] == "test_step_1"
    
    print("\n--- Simple Hybrid Memory Test PASSED! ---")

if __name__ == "__main__":
    asyncio.run(test_simple_cache())
