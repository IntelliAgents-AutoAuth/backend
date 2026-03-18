import os
import sys
import traceback
import logging
from sqlalchemy.orm import Session
from db.session import SessionLocal
from constants.cases import CaseStatus
from crud import crud_case
from services.extraction_service import fill_extracted_data_from_ehr
from agents.gap_analysis_agent import run_gap_analysis
from agents.eligibility_agent import run_eligibility_check
from agents.pa_document_agent import generate_pa_content
from services.pdf_generator import generate_pa_pdf
from utils.agent_logger import log_event

logger = logging.getLogger(__name__)

class CaseOrchestrator:
    """
    Main orchestrator for AutoAuth.
    Coordinates all agents and manages complete PA lifecycle.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id

    def _get_db(self):
        return SessionLocal()

    async def run(self, trigger: str, payload: dict = None):
        """
        Single entry point for all triggers.
        
        triggers:
        - "CASE_CREATED"
        - "DOCUMENTS_UPLOADED"
        - "STAFF_APPROVED"
        - "RETRY"
        """
        payload = payload or {}
        db = self._get_db()
        try:
            db_case = crud_case.get_case(db, case_id=self.case_id)
            if not db_case:
                logger.error(f"[orchestrator] Case {self.case_id} not found.")
                return

            current_status = db_case.status
            logger.info(f"[orchestrator] Handling trigger '{trigger}' for case {self.case_id} (Status: {current_status})")

            if trigger == "CASE_CREATED":
                await self.handle_case_created(db, db_case, payload)
            elif trigger == "DOCUMENTS_UPLOADED":
                await self.handle_documents_uploaded(db, db_case, payload)
            elif trigger == "STAFF_APPROVED":
                await self.handle_staff_approved(db, db_case, payload)
            elif trigger == "RETRY":
                # To be implemented in handle_retry
                pass
            else:
                logger.warning(f"[orchestrator] Unknown trigger: {trigger}")

        except Exception as e:
            logger.error(f"[orchestrator] Error in orchestration: {e}")
            traceback.print_exc()
            # Mark case as FAILED in DB if possible
            try:
                db_case = crud_case.get_case(db, case_id=self.case_id)
                if db_case:
                    db_case.status = CaseStatus.FAILED.value
                    db.add(db_case)
                    db.commit()
            except:
                pass
        finally:
            db.close()

    async def handle_case_created(self, db: Session, db_case, payload: dict):
        """Logic for when a case is first created."""
        
        # 1. EHR Fetching
        db_case.status = CaseStatus.EHR_FETCHING.value
        db.add(db_case)
        db.commit()
        
        log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_START", "RUNNING", "Fetching patient EHR data")
        
        try:
            fill_extracted_data_from_ehr(db, patient_id=db_case.patient_id, case_id=db_case.case_id)
            db_case.status = CaseStatus.EHR_FETCHED.value
            db.add(db_case)
            db.commit()
            log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_COMPLETE", "SUCCESS", "EHR data fetched successfully")
        except Exception as e:
            logger.error(f"[orchestrator] EHR Fetch failed: {e}")
            db_case.status = CaseStatus.FAILED.value
            db.add(db_case)
            db.commit()
            return

        # 2. Gap Analysis
        db_case.status = CaseStatus.GAP_ANALYSIS_RUNNING.value
        db.add(db_case)
        db.commit()
        
        agent_props = {
            "case_id": self.case_id,
            "patient_name": f"Patient {db_case.patient_id}",
            "pdf_path": payload.get("pdf_path")
        }
        
        result = await run_gap_analysis(agent_props)
        # Gap analysis agent updates status to GAP_FOUND or GAP_CLEARED internally
        # But we ensure it here based on its output
        
        db.refresh(db_case)
        if db_case.status == CaseStatus.GAP_CLEARED.value:
            # Continue to Eligibility automatically
            await self.handle_gap_cleared(db, db_case, payload)

    async def handle_documents_uploaded(self, db: Session, db_case, payload: dict):
        """Logic for when a document is uploaded."""
        # This is typically called from the API after the upload is persisted
        # We check if gaps are now cleared
        from api.v1.endpoints.cases import _check_and_clear_gaps 
        # Note: In a real refactor, _check_and_clear_gaps would be moved to the orchestrator or a service
        
        # For now, we assume the API has already updated the case.status to GAP_CLEARED
        # If it is GAP_CLEARED, we proceed.
        if db_case.status == CaseStatus.GAP_CLEARED.value:
            await self.handle_gap_cleared(db, db_case, payload)

    async def handle_gap_cleared(self, db: Session, db_case, payload: dict):
        """Triggered when all gaps are filled."""
        db_case.status = CaseStatus.ELIGIBILITY_RUNNING.value
        db.add(db_case)
        db.commit()
        
        log_event(self.case_id, "ORCHESTRATOR", "ELIGIBILITY_START", "RUNNING", "Starting eligibility reasoning")
        
        try:
            # We need to make eligibility agent async or wrap it
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, run_eligibility_check, {
                "case_id": self.case_id,
                "pdf_path": payload.get("pdf_path")
            })
            
            db.refresh(db_case)
            if result.get("eligible"):
                # Automatically trigger packet generation
                await self.handle_eligible(db, db_case, payload)
            else:
                db_case.status = CaseStatus.NOT_ELIGIBLE.value
                db.add(db_case)
                db.commit()
                
        except Exception as e:
            logger.error(f"[orchestrator] Eligibility failed: {e}")
            db_case.status = CaseStatus.FAILED.value
            db.add(db_case)
            db.commit()

    async def handle_eligible(self, db: Session, db_case, payload: dict):
        """Triggered when case is eligible."""
        db_case.status = CaseStatus.PACKET_GENERATING.value
        db.add(db_case)
        db.commit()
        
        log_event(self.case_id, "ORCHESTRATOR", "PACKET_GEN_START", "RUNNING", "Generating PA document package")
        
        try:
            # 1. LLM generates the text content (Cover Letter, Summary, Checklist)
            import asyncio
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, generate_pa_content, self.case_id, payload.get("pdf_path"))
            
            # 2. Extract uploaded files to attach
            uploaded_paths = []
            if db_case.uploaded_files:
                for f in db_case.uploaded_files:
                    path = f.get("file_path") or f.get("path")
                    if path and os.path.exists(path):
                        uploaded_paths.append(path)
            
            # 3. PDF builder assembles the final package
            log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_START", "RUNNING", "Building final PDF package")
            output_pdf = await loop.run_in_executor(None, generate_pa_pdf, self.case_id, content, uploaded_paths)
            
            logger.info(f"[orchestrator] PDF generated successfully: {output_pdf}")
            log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_COMPLETE", "SUCCESS", f"PDF generated: {os.path.basename(output_pdf)}")
            
            db_case.status = CaseStatus.PACKET_READY.value
            db.add(db_case)
            db.commit()
            
            # Transition to PENDING_APPROVAL for staff to review
            db_case.status = CaseStatus.PENDING_APPROVAL.value
            db.add(db_case)
            # Log the final transition
            log_event(self.case_id, "ORCHESTRATOR", "ORCHESTRATION_FLOW_COMPLETE", "SUCCESS", "Case is ready for review")
            db.commit()
            
        except Exception as e:
            logger.error(f"[orchestrator] Packet generation failed: {e}")
            log_event(self.case_id, "ORCHESTRATOR", "PACKET_GEN_FAILED", "FAILED", str(e))
            db_case.status = CaseStatus.FAILED.value
            db.add(db_case)
            db.commit()

    async def handle_staff_approved(self, db: Session, db_case, payload: dict):
        """Logic for when staff approves the PA package for submission."""
        
        # 1. Transition to SUBMITTED
        db_case.status = CaseStatus.SUBMITTED.value
        db.add(db_case)
        db.commit()
        
        log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_START", "RUNNING", "Submitting package to insurance portal")
        
        try:
            # Get the path to the generated PDF
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            output_dir = os.path.join(backend_dir, "uploads", "generated")
            files = [f for f in os.listdir(output_dir) if f.startswith(f"PA_{self.case_id}_") and f.endswith(".pdf")]
            
            if not files:
                raise Exception("Cannot submit: No generated PDF package found.")
            
            files.sort(reverse=True)
            latest_pdf_path = os.path.join(output_dir, files[0])
            
            # Send HTTP request to local payer endpoint
            import httpx
            
            # Using httpx.AsyncClient since we are in an async function
            async with httpx.AsyncClient() as client:
                with open(latest_pdf_path, "rb") as pdf_file:
                    files_payload = {
                        "package_pdf": (os.path.basename(latest_pdf_path), pdf_file, "application/pdf")
                    }
                    
                    from tools.ehr_fetcher import fetch_extracted_data_by_case
                    ext_data = fetch_extracted_data_by_case(str(db_case.case_id), extract_pdf_text=False) or {}
                    p_name = f"{ext_data.get('patient_first_name') or ''} {ext_data.get('patient_last_name') or ''}".strip()
                    if not p_name:
                        p_name = f"Patient {db_case.patient_id}"
                    diag = ext_data.get("primary_diagnosis") or ext_data.get("diagnosis") or db_case.icd10_code or ""
                    
                    data_payload = {
                        "case_id": str(db_case.case_id),
                        "patient_name": str(p_name),
                        "cpt_code": str(ext_data.get('cpt_code') or db_case.cpt_code or ""),
                        "diagnosis": str(diag)
                    }
                    
                    response = await client.post(
                        "http://localhost:8000/api/v1/payer/submissions",
                        data=data_payload,
                        files=files_payload,
                        timeout=30.0
                    )
                    response.raise_for_status()
            
            # 2. Transition to TRACKING
            db_case.status = CaseStatus.TRACKING.value
            db.add(db_case)
            db.commit()
            
            log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_COMPLETE", "SUCCESS", "Package accepted by payer. Now tracking status.")
            
        except Exception as e:
            logger.error(f"[orchestrator] Submission failed: {e}")
            log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_FAILED", "FAILED", str(e))
            db_case.status = CaseStatus.FAILED.value
            db.add(db_case)
            db.commit()
