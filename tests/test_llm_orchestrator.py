import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Mock dependencies before importing CaseOrchestrator
sys.modules['db.base'] = MagicMock()
sys.modules['db.session'] = MagicMock()
sys.modules['crud.crud_case'] = MagicMock()
sys.modules['services.extraction_service'] = MagicMock()
sys.modules['agents.gap_analysis_agent'] = MagicMock()
sys.modules['agents.eligibility_agent'] = MagicMock()
sys.modules['agents.pa_document_agent'] = MagicMock()
sys.modules['services.pdf_generator'] = MagicMock()
sys.modules['utils.agent_logger'] = MagicMock()

# Mock CaseStatus and constants.cases
mock_constants = MagicMock()
mock_constants.CaseStatus.EHR_FETCHED.value = "EHR_FETCHED"
mock_constants.CaseStatus.PACKET_READY.value = "PACKET_READY"
mock_constants.CaseStatus.PENDING_APPROVAL.value = "PENDING_APPROVAL"
mock_constants.CaseStatus.FAILED.value = "FAILED"
sys.modules['constants.cases'] = mock_constants

# Add backend to path
sys.path.append(os.getcwd())

from orchestrator.case_orchestrator import CaseOrchestrator
from constants.cases import CaseStatus

async def test_llm_orchestrator_decision():
    """Test that the orchestrator calls the LLM and follows its decision."""
    case_id = "test-case-123"
    orchestrator = CaseOrchestrator(case_id)
    
    # Mock DB and Case
    mock_db = MagicMock()
    orchestrator._get_db = MagicMock(return_value=mock_db)
    
    mock_case = MagicMock()
    mock_case.case_id = case_id
    mock_case.patient_id = "P1"
    mock_case.status = "CREATED"
    mock_case.audit_log = []
    
    # Mock Memory
    orchestrator.memory = MagicMock()
    orchestrator.memory.summary.return_value = "No history."
    orchestrator.memory.succeeded.return_value = False
    
    # Mock LLM Response
    mock_llm_response = MagicMock()
    mock_llm_response.content = '{"thinking": "Starting with data fetch", "next_step": "ehr_fetch"}'
    
    with patch("orchestrator.case_orchestrator.ChatGoogleGenerativeAI") as MockLLMClass:
        mock_llm_instance = MockLLMClass.return_value
        mock_llm_instance.ainvoke = AsyncMock(return_value=mock_llm_response)
        
        # Mock execute_step to return failure to avoid further loops for now
        orchestrator._execute_step = AsyncMock(return_value={"event": "FAILED"})
        
        # Run orchestrator
        with patch("orchestrator.case_orchestrator.crud_case.get_case", return_value=mock_case):
            await orchestrator.run("CASE_CREATED")
            
        # Verify LLM was called
        assert mock_llm_instance.ainvoke.called
        print("✅ LLM was called correctly.")
        
        # Verify execute_step was called with the LLM's suggested step
        orchestrator._execute_step.assert_called_with("ehr_fetch", mock_db, mock_case, {})
        print("✅ Orchestrator followed LLM decision 'ehr_fetch'.")

if __name__ == "__main__":
    asyncio.run(test_llm_orchestrator_decision())
