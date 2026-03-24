"""
CaseOrchestrator — State Machine + Memory
==========================================

Architecture
------------
  run(trigger)
    → memory.load()              # recall what agents have already been called
    → current_step = _resolve_next_step(trigger, db_status)
    → while current_step:
          # skip if already ran successfully
          if memory.succeeded(current_step): ...
          result = await _execute_step(current_step, memory)
          memory.record(current_step, inputs, result)
          db_status = db_case.status   (updated by agent)
          current_step = _resolve_next_step(result["event"], db_status)
    → memory.save()

Agents never call each other and never decide what comes next.
The orchestrator owns all routing logic via TRANSITIONS.
"""

import os
import asyncio
import traceback
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

import db.base  # noqa: F401 — registers all models with SQLAlchemy metadata (fixes FK resolution)
from db.session import SessionLocal
from constants.cases import CaseStatus
from crud import crud_case
from services.extraction_service import fill_extracted_data_from_ehr
from agents.gap_analysis_agent import run_gap_analysis
from agents.eligibility_agent import run_eligibility_check
from agents.pa_document_agent import generate_pa_content
from services.pdf_generator import generate_pa_pdf
from utils.agent_logger import log_event
from orchestrator.memory import OrchestratorMemory

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# STATE MACHINE  —  (event, current_db_status) → next_step
# None status means "any status is fine" (wildcard)
# ─────────────────────────────────────────────────────────────
TRANSITIONS: dict[tuple[str, str | None], str] = {
    # Trigger              DB Status (after agent writes it)     Next step
    ("CASE_CREATED",       None):                               "ehr_fetch",
    ("EHR_FETCH_DONE",     CaseStatus.EHR_FETCHED.value):      "gap_analysis",
    ("GAP_CLEARED",        CaseStatus.GAP_CLEARED.value):      "eligibility",
    ("DOCUMENTS_UPLOADED", CaseStatus.GAP_CLEARED.value):      "eligibility",
    ("ELIGIBLE",           "APPROVED"):                         "packet_gen",
    ("PACKET_DONE",        CaseStatus.PACKET_READY.value):      "pending_approval",
    ("STAFF_APPROVED",     CaseStatus.PENDING_APPROVAL.value):  "submit",
}


class CaseOrchestrator:
    """
    Orchestrator for AutoAuth.

    Controls the full PA lifecycle via a state machine.
    Uses OrchestratorMemory to track which agents have already been called
    and what results they returned — so it never re-runs a completed step
    and can pass prior outputs downstream without re-fetching from DB.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.memory = OrchestratorMemory(case_id)

    def _get_db(self):
        return SessionLocal()

    # ─────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────

    async def run(self, trigger: str, payload: dict = None):
        """
        Single entry point for all external triggers:
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

            # Load prior agent call history for this case
            self.memory.load(db)
            logger.info(
                f"[orchestrator] Trigger='{trigger}' | "
                f"Status={db_case.status} | "
                f"Memory so far: {self.memory.summary()}"
            )

            if trigger == "RETRY":
                await self._handle_retry(db, db_case, payload)
                return

            # Resolve the first step from the trigger
            current_step = self._resolve_next_step(trigger, db_case.status)

            # State machine loop — orchestrator drives every transition
            while current_step:
                # Skip steps the orchestrator already successfully completed
                if self.memory.succeeded(current_step):
                    logger.info(
                        f"[orchestrator] Skipping '{current_step}' — already ran successfully."
                    )
                    # Still need to figure out the next step after the skipped one
                    prior_result = self.memory.get_last_result(current_step)
                    event = prior_result.get("event", "") if prior_result else ""
                    db.refresh(db_case)
                    current_step = self._resolve_next_step(event, db_case.status)
                    continue

                logger.info(f"[orchestrator] Executing step: '{current_step}'")
                log_event(self.case_id, "ORCHESTRATOR", f"STEP_START_{current_step.upper()}", "RUNNING", f"Starting step: {current_step}")

                result = await self._execute_step(current_step, db, db_case, payload)

                # result must always contain an "event" key so the transition table works
                event = result.get("event", "FAILED")

                # Record what we sent to the agent and what came back
                self.memory.record(
                    step=current_step,
                    inputs={"case_id": self.case_id, "payload_keys": list(payload.keys())},
                    result=result,
                    status="SUCCESS" if event != "FAILED" else "FAILED",
                )
                self.memory.save(db)

                if event == "FAILED":
                    logger.error(f"[orchestrator] Step '{current_step}' failed. Halting.")
                    break

                # Refresh DB state (agents update status internally)
                db.refresh(db_case)
                log_event(self.case_id, "ORCHESTRATOR", f"STEP_DONE_{current_step.upper()}", "SUCCESS", f"Completed step: {current_step} → event: {event}")

                current_step = self._resolve_next_step(event, db_case.status)

            logger.info(
                f"[orchestrator] Flow complete for {self.case_id}. "
                f"History: {self.memory.summary()}"
            )

        except Exception as e:
            logger.error(f"[orchestrator] Unhandled error: {e}")
            traceback.print_exc()
            try:
                db_case = crud_case.get_case(db, case_id=self.case_id)
                if db_case:
                    db_case.status = CaseStatus.FAILED.value
                    db.add(db_case)
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()

    # ─────────────────────────────────────────
    # TRANSITION TABLE RESOLVER
    # ─────────────────────────────────────────

    def _resolve_next_step(self, event: str, db_status: str) -> str | None:
        """
        Look up the next step from the transition table.
        First tries exact (event, status) match, then (event, None) wildcard.
        Returns None if no transition exists (i.e. stop).
        """
        next_step = TRANSITIONS.get((event, db_status))
        if next_step is None:
            next_step = TRANSITIONS.get((event, None))
        return next_step

    # ─────────────────────────────────────────
    # STEP EXECUTOR DISPATCHER
    # ─────────────────────────────────────────

    async def _execute_step(
        self, step: str, db: Session, db_case, payload: dict
    ) -> dict:
        """
        Dispatch to the correct agent/service for the given step.
        Every step must return a dict with at least {"event": str}.
        """
        try:
            if step == "ehr_fetch":
                return await self._step_ehr_fetch(db, db_case, payload)
            elif step == "gap_analysis":
                return await self._step_gap_analysis(db, db_case, payload)
            elif step == "eligibility":
                return await self._step_eligibility(db, db_case, payload)
            elif step == "packet_gen":
                return await self._step_packet_gen(db, db_case, payload)
            elif step == "pending_approval":
                return await self._step_pending_approval(db, db_case)
            elif step == "submit":
                return await self._step_submit(db, db_case)
            else:
                logger.warning(f"[orchestrator] Unknown step: '{step}'")
                return {"event": "FAILED", "error": f"Unknown step: {step}"}
        except Exception as e:
            logger.error(f"[orchestrator] Step '{step}' raised: {e}")
            traceback.print_exc()
            try:
                db_case.status = CaseStatus.FAILED.value
                db.add(db_case)
                db.commit()
            except Exception:
                pass
            return {"event": "FAILED", "error": str(e)}

    # ─────────────────────────────────────────
    # INDIVIDUAL STEPS
    # Each returns {"event": "...", ...extra}
    # ─────────────────────────────────────────

    async def _step_ehr_fetch(self, db: Session, db_case, payload: dict) -> dict:
        """Step 1 — Fetch and extract EHR data for the patient."""
        db_case.status = CaseStatus.EHR_FETCHING.value
        db.add(db_case)
        db.commit()

        log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_START", "RUNNING", "Fetching patient EHR data")

        fill_extracted_data_from_ehr(db, patient_id=db_case.patient_id, case_id=db_case.case_id)

        db_case.status = CaseStatus.EHR_FETCHED.value
        db.add(db_case)
        db.commit()
        log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_COMPLETE", "SUCCESS", "EHR data fetched")

        return {"event": "EHR_FETCH_DONE"}

    async def _step_gap_analysis(self, db: Session, db_case, payload: dict) -> dict:
        """Step 2 — Run gap analysis LLM agent."""
        agent_props = {
            "case_id": self.case_id,
            "patient_name": f"Patient {db_case.patient_id}",
            "pdf_path": payload.get("pdf_path"),
        }
        result = await run_gap_analysis(agent_props)

        db.refresh(db_case)
        new_status = db_case.status

        # Determine the outgoing event from DB status (agent wrote it)
        if new_status == CaseStatus.GAP_CLEARED.value:
            event = "GAP_CLEARED"
        elif new_status == CaseStatus.GAP_FOUND.value:
            event = "GAP_FOUND"   # → waiting for docs, no next step yet
        else:
            event = "FAILED"

        return {"event": event, "gap_result": result.get("output")}

    async def _step_eligibility(self, db: Session, db_case, payload: dict) -> dict:
        """Step 3 — Run eligibility check.
        
        Reuses gap analysis output from memory if available,
        so we don't re-fetch data the orchestrator already has.
        """
        # The orchestrator remembers the gap analysis result — pass it along as context
        gap_output = self.memory.get_last_result("gap_analysis")
        if gap_output:
            logger.info(
                f"[orchestrator] Passing prior gap_analysis result into eligibility for {self.case_id}"
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            run_eligibility_check,
            {
                "case_id": self.case_id,
                "pdf_path": payload.get("pdf_path"),
                # Gap context is implicitly available via DB; we log it in memory
                "_gap_context": gap_output,
            },
        )

        db.refresh(db_case)

        if result.get("eligible"):
            event = "ELIGIBLE"
        else:
            event = "NOT_ELIGIBLE"

        return {"event": event, "eligibility_result": result}

    async def _step_packet_gen(self, db: Session, db_case, payload: dict) -> dict:
        """Step 4 — Generate the PA document package."""
        db_case.status = CaseStatus.PACKET_GENERATING.value
        db.add(db_case)
        db.commit()

        log_event(self.case_id, "ORCHESTRATOR", "PACKET_GEN_START", "RUNNING", "Generating PA document package")

        loop = asyncio.get_event_loop()

        # Memory gives us access to both gap + eligibility outputs if needed by PA agent
        eligibility_output = self.memory.get_last_result("eligibility")
        if eligibility_output:
            logger.info(f"[orchestrator] PA gen has access to eligibility result from memory.")

        content = await loop.run_in_executor(
            None, generate_pa_content, self.case_id, payload.get("pdf_path")
        )

        # Collect uploaded file paths to attach to the PDF
        uploaded_paths = []
        if db_case.uploaded_files:
            for f in db_case.uploaded_files:
                path = f.get("file_path") or f.get("path")
                if path and os.path.exists(path):
                    uploaded_paths.append(path)

        log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_START", "RUNNING", "Building final PDF package")
        output_pdf = await loop.run_in_executor(
            None, generate_pa_pdf, self.case_id, content, uploaded_paths
        )

        logger.info(f"[orchestrator] PDF generated: {output_pdf}")
        log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_COMPLETE", "SUCCESS", f"PDF: {os.path.basename(output_pdf)}")

        db_case.status = CaseStatus.PACKET_READY.value
        db.add(db_case)
        db.commit()

        return {"event": "PACKET_DONE", "pdf_path": output_pdf}

    async def _step_pending_approval(self, db: Session, db_case) -> dict:
        """Step 5 — Move case to PENDING_APPROVAL for staff review."""
        db_case.status = CaseStatus.PENDING_APPROVAL.value
        db.add(db_case)
        db.commit()
        log_event(self.case_id, "ORCHESTRATOR", "ORCHESTRATION_FLOW_COMPLETE", "SUCCESS", "Case ready for staff review")
        # Stop here — next trigger comes externally ("STAFF_APPROVED")
        return {"event": "AWAITING_STAFF"}

    async def _step_submit(self, db: Session, db_case) -> dict:
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
        log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_START", "RUNNING", "Submitting to payer")

        await asyncio.sleep(2)  # Simulated network latency

        db_case.status = CaseStatus.TRACKING.value
        db.add(db_case)
        db.commit()
        log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_COMPLETE", "SUCCESS", "Package accepted by payer. Tracking.")

        return {"event": "SUBMITTED"}

    # ─────────────────────────────────────────
    # RETRY HANDLER
    # ─────────────────────────────────────────

    async def _handle_retry(self, db: Session, db_case, payload: dict):
        """
        Re-run the last FAILED step only, using prior memory context.
        All previously SUCCEEDED steps are skipped automatically.
        """
        logger.info(f"[orchestrator] RETRY requested for {self.case_id}")
        log_event(self.case_id, "ORCHESTRATOR", "RETRY_STARTED", "RUNNING", "Retrying last failed step")

        # Find the last failed step from memory
        history = self.memory.get_history()
        last_failed = next(
            (e["step"] for e in reversed(history) if e["status"] == "FAILED"),
            None
        )

        if not last_failed:
            logger.warning(f"[orchestrator] No failed step found in memory, nothing to retry.")
            return

        logger.info(f"[orchestrator] Retrying step: '{last_failed}'")
        result = await self._execute_step(last_failed, db, db_case, payload)
        event = result.get("event", "FAILED")

        self.memory.record(
            step=last_failed,
            inputs={"case_id": self.case_id, "retry": True},
            result=result,
            status="SUCCESS" if event != "FAILED" else "FAILED",
        )
        self.memory.save(db)

        # If retry succeeded, continue the main flow
        if event != "FAILED":
            db.refresh(db_case)
            next_step = self._resolve_next_step(event, db_case.status)
            if next_step:
                # Resume from where we left off
                await self.run(event, payload)
