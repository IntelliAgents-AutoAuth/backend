import os
import sys
import traceback
import logging
from sqlalchemy.orm import Session
from db.session import SessionLocal
from constants.cases import CaseStatus
from crud import crud_case
import httpx

logger = logging.getLogger(__name__)

# Basic Event logger (assuming the old one was removed or isn't strictly necessary for the minimal POC)
def log_event(case_id, source, event, status, message):
    logger.info(f"[{source}] {event}: {message} ({status})")

    with SessionLocal() as db:
        db_case = crud_case.get_case(db, case_id=case_id)
        if db_case:
            new_log = {
                "timestamp": "Now",
                "source": source,
                "event": event,
                "status": status,
                "message": message
            }
            logs = list(db_case.audit_log) if db_case.audit_log else []
            logs.append(new_log)
            db_case.audit_log = logs
            db.add(db_case)
            db.commit()


class CaseOrchestrator:
    """
    Rebuilt main orchestrator class just for the payer submission logic.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id

    def _get_db(self):
        return SessionLocal()

    async def run(self, trigger: str, payload: dict = None):
        """
        Single entry point for triggers. 
        Focuses only on 'STAFF_APPROVED' for this task.
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

            if trigger == "STAFF_APPROVED":
                await self.handle_staff_approved(db, db_case, payload)
            else:
                logger.warning(f"[orchestrator] Rebuilt orchestrator doesn't support trigger: {trigger}")

        except Exception as e:
            logger.error(f"[orchestrator] Error in orchestration: {e}")
            traceback.print_exc()
        finally:
            db.close()

    async def handle_staff_approved(self, db: Session, db_case, payload: dict):
        """Logic for when staff approves the PA package for submission."""
        
        # 1. Transition to SUBMITTED locally
        db_case.status = CaseStatus.SUBMITTED.value
        db.add(db_case)
        db.commit()
        
        log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_START", "RUNNING", "Submitting package to insurance portal")
        
        try:
            # 2. Find the generated PDF
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            output_dir = os.path.join(backend_dir, "uploads", "generated")
            files = [f for f in os.listdir(output_dir) if f.startswith(f"PA_{self.case_id}_") and f.endswith(".pdf")]
            
            if not files:
                raise Exception("Cannot submit: No generated PDF package found.")
            
            files.sort(reverse=True)
            latest_pdf_path = os.path.join(output_dir, files[0])
            
            # Send HTTP request to local payer endpoint using httpx
            async with httpx.AsyncClient() as client:
                with open(latest_pdf_path, "rb") as pdf_file:
                    files_payload = {
                        "package_pdf": (os.path.basename(latest_pdf_path), pdf_file, "application/pdf")
                    }
                    
                    data_payload = {
                        "case_id": str(db_case.case_id),
                        "patient_name": f"Patient {db_case.patient_id}",
                        "cpt_code": str(db_case.cpt_code or ""),
                        "diagnosis": str(db_case.icd10_code or "")
                    }
                    
                    response = await client.post(
                        "http://localhost:8000/api/v1/payer/submissions",
                        data=data_payload,
                        files=files_payload,
                        timeout=30.0
                    )
                    response.raise_for_status()
            
            # 3. Transition to TRACKING
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
