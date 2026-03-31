"""
CaseOrchestrator — Intelligent State Machine & Agent Coordination
==================================================================

The CaseOrchestrator is the central "brain" of the IntelliAgents platform. It manages
the end-to-end lifecycle of a Prior Authorization (PA) case using a combination of
deterministic logic and an LLM-based Supervisor.

Key Features:
-------------
1. **Dynamic Routing**: Uses an LLM Supervisor to decide the next logical step 
   based on the current case status, historical actions, and new triggers.
2. **State Persistence**: Integrates with OrchestratorMemory to ensure that 
   successful steps are never redundantly re-run, saving both time and LLM costs.
3. **Trigger-Based Execution**: Responds to external events (e.g., file uploads, 
   staff approvals, sync requests) to move a case through its lifecycle.
4. **Resilience**: Features built-in retry logic that resumes from the last 
   failed step while maintaining full context.

Flow Architecture:
------------------
    run(trigger)
      → memory.load()              # Recall previous agent activity
      → _resolve_next_step_llm()   # AI decides where to go next
      → while current_step:
            # Check if we can skip this step (optimization)
            if memory.succeeded(current_step) and not rerun_needed: 
                continue
                
            # Execute the core logic for this step
            result = await _execute_step(current_step)
            
            # Record result and transition to next step
            memory.record(current_step, result)
            current_step = _resolve_next_step(result["event"], db_status)
      → memory.save()              # Commit state to database
"""

import os
import json
import time
import asyncio
import traceback
import logging
from datetime import datetime, timezone
from functools import partial
from sqlalchemy.orm import Session
from langchain_google_genai import ChatGoogleGenerativeAI

from db import SessionLocal, get_case
from services import (
    fill_extracted_data_from_ehr,
    generate_pa_pdf,
    summarize_case_documents
)
from agents import (
    run_gap_analysis,
    run_gap_analysis_delta,
    run_eligibility_check,
    generate_pa_content
)
from utils.logger import log_event
from utils.llm_util import get_keys, get_model_order
from orchestrator.memory import OrchestratorMemory
from constants import CaseStatus
from prompts import ORCHESTRATOR_SYSTEM_PROMPT, CONTEXT_TEMPLATE

logger = logging.getLogger(__name__)

# Process-local lock table to avoid concurrent duplicate runs for same case.
_CASE_RUN_LOCKS: dict[str, asyncio.Lock] = {}


# ─────────────────────────────────────────────────────────────
# STEP REGISTRY — Metadata for the LLM Supervisor
# ─────────────────────────────────────────────────────────────
STEP_REGISTRY = {
    "ehr_fetch": {
        "description": "Fetch and extract medical data from the EHR system for a specific patient.",
        "expected_event": "EHR_FETCH_DONE",
    },
    "gap_analysis": {
        "description": "An AI agent checks for missing clinical data needed for the PA based on payer policies.",
        "expected_event": "GAP_CLEARED or GAP_FOUND",
    },
    "eligibility": {
        "description": "An AI agent verifies if the patient qualifies for the procedure using the extracted medical evidence.",
        "expected_event": "ELIGIBLE or NOT_ELIGIBLE",
    },
    "packet_gen": {
        "description": "Generate the final PA document package (PDF) with all clinical justifications attached.",
        "expected_event": "PACKET_DONE",
    },
    "pending_approval": {
        "description": "Prepare the case for human (staff) review. The flow pauses here.",
        "expected_event": "AWAITING_STAFF",
    },
    "submit": {
        "description": "Submit the final PA package to the insurance payer.",
        "expected_event": "SUBMITTED",
    },
}


class CaseOrchestrator:
    """
    The CaseOrchestrator class manages the Prior Authorization workflow.

    It acts as a state machine controller, using 'OrchestratorMemory' to track
    the execution history of various agents (EHR Fetch, Gap Analysis, Eligibility, etc.).
    This ensures that the system is both efficient (no redundant work) and 
    context-aware (downstream agents receive results from upstream ones).

    Attributes:
        case_id (str): The unique identifier for the medical case being processed.
        memory (OrchestratorMemory): The persistent history of agent calls for this case.
        _max_steps (int): Safety limit to prevent infinite loops in the state machine.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.memory = OrchestratorMemory(case_id)
        self._max_steps = 10

    def _get_db(self):
        return SessionLocal()

    def _should_rerun_step(self, step: str, trigger: str) -> bool:
        """
        Decide whether a previously successful step should be rerun for this trigger.
        """
        if trigger == "DOCUMENTS_UPLOADED" and step in {"gap_analysis", "eligibility"}:
            return True
        if trigger == "ELIGIBILITY_REQUESTED" and step == "eligibility":
            return True
        if trigger == "SYNC_REQUESTED" and step in {"ehr_fetch", "gap_analysis"}:
            return True
        if trigger == "GENERATE_PACKET_REQUESTED" and step == "packet_gen":
            return True
        return False

    # ─────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────

    async def run(self, trigger: str, payload: dict = None):
        """
        The main entrance for all case processing activities.

        This method is triggered by external events such as:
          - "CASE_CREATED": Initial setup and EHR data retrieval.
          - "DOCUMENTS_UPLOADED": New clinical evidence added by the user.
          - "ELIGIBILITY_REQUESTED": Manual start of the AI clinical check.
          - "STAFF_APPROVED": A human reviewer has confirmed the PA packet.
          - "RETRY": Manual or automatic attempt to fix a failed step.

        It manages concurrency using an asynchronous lock per case_id to 
        prevent duplicate processing runs.
        """
        payload = payload or {}
        db = self._get_db()
        case_lock = _CASE_RUN_LOCKS.setdefault(self.case_id, asyncio.Lock())

        if case_lock.locked() and trigger != "RETRY":
            logger.info(
                f"[orchestrator] Ignoring trigger '{trigger}' for {self.case_id}: run already in progress."
            )
            return

        await case_lock.acquire()

        try:
            db_case = get_case(db, case_id=self.case_id)
            if not db_case:
                logger.error(f"[orchestrator] Case {self.case_id} not found.")
                return

            # Load prior agent call history for this case
            self.memory.load(db)
            
            log_event(
                self.case_id,
                "ORCHESTRATOR",
                "ORCHESTRATOR_STARTED", 
                "RUNNING",
                f"Case processing started (trigger: {trigger})",
                db_session=db
            )
            db.commit()
            
            logger.info(
                f"[orchestrator] Trigger='{trigger}' | "
                f"Status={db_case.status} | "
                f"Memory so far: {self.memory.summary()}"
            )

            # OPTIMIZATION 7: EHR Cache in Memory - fetch once at start, pass to all agents
            try:
                from tools.ehr_fetcher import fetch_extracted_data_by_case
                ehr_start = time.time()
                ehr_data = fetch_extracted_data_by_case(self.case_id)
                if ehr_data:
                    self.memory.set_cached_data("ehr_data", ehr_data)
                    ehr_elapsed = time.time() - ehr_start
                    logger.info(
                        f"[orchestrator] Pre-fetched and cached EHR data for {self.case_id} "
                        f"({ehr_elapsed:.2f}s) — all agents will read from cache"
                    )
            except Exception as e:
                logger.warning(f"[orchestrator] Failed to pre-fetch EHR data: {e}")

            in_progress_statuses = {
                CaseStatus.EHR_FETCHING.value,
                CaseStatus.GAP_ANALYSIS_RUNNING.value,
                CaseStatus.ELIGIBILITY_RUNNING.value,
                CaseStatus.PACKET_GENERATING.value,
            }
            # Allow DOCUMENTS_UPLOADED to bypass in-progress check (enables re-analysis during eligibility)
            if trigger != "RETRY" and trigger != "DOCUMENTS_UPLOADED" and db_case.status in in_progress_statuses:
                logger.info(
                    f"[orchestrator] Ignoring trigger '{trigger}' for {self.case_id}: "
                    f"case is already in-progress with status={db_case.status}."
                )
                return

            if trigger == "RETRY":
                await self._handle_retry(db, db_case, payload)
                return

            # Store trigger for use by steps (Optimization 4: Delta Analysis needs to know trigger)
            self._current_trigger = trigger

            # AI Thinking & Step resolution
            # Optimization: For deterministic triggers, skip expensive LLM call
            DETERMINISTIC_TRIGGERS = {
                "CASE_CREATED",
                "SYNC_REQUESTED",
                "ELIGIBILITY_REQUESTED",
                "GENERATE_PACKET_REQUESTED",
            }
            
            # Special case: DOCUMENTS_UPLOADED during in-progress should use LLM (more intelligent)
            # This prevents hardcoded routing from breaking in edge cases
            use_llm_for_document_upload = (
                trigger == "DOCUMENTS_UPLOADED" and 
                db_case.status in {
                    CaseStatus.ELIGIBILITY_RUNNING.value,
                    CaseStatus.PACKET_GENERATING.value,
                }
            )
            
            if trigger in DETERMINISTIC_TRIGGERS and not use_llm_for_document_upload:
                # Skip LLM Supervisor - we already know the next step for these triggers
                logger.info(f"[orchestrator] Using deterministic path for trigger={trigger} (skipping LLM Supervisor)")
                current_step = self._resolve_next_step(trigger, db_case.status)
                thinking = f"Deterministic route (no LLM needed) for trigger={trigger}"
            else:
                # For ambiguous triggers OR document uploads during in-progress, use LLM to decide
                if use_llm_for_document_upload:
                    logger.info(f"[orchestrator] Using LLM Supervisor for DOCUMENTS_UPLOADED (case in-progress)")
                else:
                    logger.info(f"[orchestrator] Using LLM Supervisor for ambiguous trigger={trigger}")
                decision = await self._resolve_next_step_llm(db, db_case, trigger, payload)
                current_step = decision.get("next_step")
                thinking = decision.get("thinking", "No explanation provided.")

            # State machine loop
            executed_steps = 0
            while current_step:
                executed_steps += 1
                if executed_steps > self._max_steps:
                    logger.error(
                        f"[orchestrator] Safety stop for {self.case_id}: exceeded max steps ({self._max_steps})."
                    )
                    break

                # Skip steps the orchestrator already successfully completed
                if self.memory.succeeded(current_step) and not self._should_rerun_step(current_step, trigger):
                    logger.info(f"[orchestrator] Skipping '{current_step}' — already ran successfully.")
                    prior_result = self.memory.get_last_result(current_step)
                    event = prior_result.get("event", "") if prior_result else ""
                    db.refresh(db_case)

                    # Use deterministic transition after a successful prior step to avoid
                    # repeated LLM supervisor calls for already-completed paths.
                    current_step = self._resolve_next_step(event, db_case.status)
                    thinking = "Skipped previously successful step; advanced using deterministic transition."
                    continue

                logger.info(f"[orchestrator] Executing step: '{current_step}' | Thinking: {thinking}")
                log_event(self.case_id, "ORCHESTRATOR", f"STEP_START_{current_step.upper()}", "RUNNING", f"LLM Decision: {thinking}", db_session=db)
                # Ensure start logs are anchored before execution
                db.commit()
                db.refresh(db_case)

                result = await self._execute_step(current_step, db, db_case, payload)
                event = result.get("event", "FAILED")

                # Record decision and execution
                self.memory.record(
                    step=current_step,
                    inputs={
                        "case_id": self.case_id, 
                        "payload_keys": list(payload.keys()),
                        "llm_thinking": thinking
                    },
                    result=result,
                    status="SUCCESS" if event != "FAILED" else "FAILED",
                )
                self.memory.save(db)

                if event == "FAILED":
                    logger.error(f"[orchestrator] Step '{current_step}' failed. Halting.")
                    break

                # Refresh DB state to ensure we have the absolute latest audit_log
                # (in case the agent used its own session internally)
                db.refresh(db_case)

                current_step = self._resolve_next_step(event, db_case.status)

            logger.info(
                f"[orchestrator] Flow complete for {self.case_id}. "
                f"History: {self.memory.summary()}"
            )

        except Exception as e:
            logger.exception(f"[orchestrator] Unhandled error: {e}")
            try:
                db_case = get_case(db, case_id=self.case_id)
                if db_case:
                    db_case.status = CaseStatus.FAILED.value
                    db.add(db_case)
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()
            if case_lock.locked():
                case_lock.release()

    # ─────────────────────────────────────────
    # LLM SUPERVISOR RESOLVER
    # ─────────────────────────────────────────

    async def _resolve_next_step_llm(
        self, db: Session, db_case, last_event: str, payload: dict
    ) -> dict:
        """
        Consults the Supervisor LLM to intelligently determine the next step.

        Unlike a hardcoded state machine, this 'AI Supervisor' evaluates:
        1. The global Step Registry (what is possible).
        2. The Case History (what has already happened).
        3. The current Patient Context (EHR status, file uploads).

        This allows for complex branching logic, such as jumping back to 
        Gap Analysis if a newly uploaded document might clear a previous gap.

        Returns:
            dict: Contains "thinking" (the reasoning) and "next_step" (the selected action).
        """
        try:
            # Model order is centrally managed in utils.llm_util
            model_order = get_model_order("orchestrator_supervisor")

            # Prepare Step Registry Description
            step_registry_desc = "\n".join(
                [f"- {name}: {info['description']}" for name, info in STEP_REGISTRY.items()]
            )

            # System Prompt
            system_msg = ORCHESTRATOR_SYSTEM_PROMPT.format(
                step_registry_desc=step_registry_desc
            )

            # Context
            patient_info = f"Patient ID {db_case.patient_id}"
            history_summary = self.memory.summary()

            context_msg = CONTEXT_TEMPLATE.format(
                case_id=self.case_id,
                patient_info=patient_info,
                db_status=db_case.status,
                last_event=last_event,
                history_summary=history_summary,
            )

            logger.info(
                f"[orchestrator] Calling Supervisor LLM for decision on {self.case_id} "
                f"with fallback order: {model_order}"
            )

            all_keys = get_keys()
            response = None
            last_model_error = None

            if not all_keys:
                raise RuntimeError("No GOOGLE_API_KEY values found for orchestrator supervisor.")

            for key_index, api_key in enumerate(all_keys):
                for model_name in model_order:
                    try:
                        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
                        response = await llm.ainvoke([
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": context_msg}
                        ])
                        logger.info(
                            f"[orchestrator] Supervisor LLM used key {key_index + 1}/{len(all_keys)} with model: {model_name}"
                        )
                        break
                    except Exception as model_err:
                        last_model_error = model_err
                        logger.warning(
                            f"[orchestrator] Supervisor failed on key {key_index + 1}/{len(all_keys)} model '{model_name}': {model_err}. Trying next model..."
                        )
                if response is not None:
                    break

            if response is None:
                raise RuntimeError(f"All orchestrator models failed. Last error: {last_model_error}")

            # Parse JSON response
            content = response.content.strip()
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            
            decision = json.loads(content)
            
            # Validation: next_step must be in registry or None
            step = decision.get("next_step")
            if step and step not in STEP_REGISTRY:
                logger.warning(f"[orchestrator] LLM suggested unknown step: {step}. Falling back to None.")
                decision["next_step"] = None

            # Trigger-aware guardrail: use deterministic first-step for external trigger entry points.
            external_triggers = {
                "CASE_CREATED",
                "SYNC_REQUESTED",
                "DOCUMENTS_UPLOADED",
                "ELIGIBILITY_REQUESTED",
                "STAFF_APPROVED",
                "GENERATE_PACKET_REQUESTED",
            }
            if last_event in external_triggers:
                fallback_step = self._resolve_next_step(last_event, db_case.status)
                if decision.get("next_step") != fallback_step:
                    logger.warning(
                        f"[orchestrator] For trigger '{last_event}', overriding LLM step "
                        f"'{decision.get('next_step')}' with deterministic step '{fallback_step}'."
                    )
                    decision["next_step"] = fallback_step
                
            return decision

        except Exception as e:
            logger.error(f"[orchestrator] Supervisor LLM error: {e}")
            # Fallback to old deterministic transition if LLM fails
            fallback_step = self._resolve_next_step(last_event, db_case.status)
            return {
                "thinking": f"LLM error occurred: {e}. Falling back to deterministic map.",
                "next_step": fallback_step
            }

    def _resolve_next_step(self, event: str, db_status: str) -> str | None:
        """
        Old deterministic transition table lookup (now used as a fallback).
        """
        # Hardcoded fallback logic since we removed the global TRANSITIONS constant
        FALLBACK_MAP = {
            ("CASE_CREATED",       None):                               "ehr_fetch",
            ("SYNC_REQUESTED",     None):                               "ehr_fetch",
            ("EHR_FETCH_DONE",     CaseStatus.EHR_FETCHED.value):      "gap_analysis",
            ("GAP_CLEARED",        CaseStatus.GAP_CLEARED.value):      "eligibility",
            ("DOCUMENTS_UPLOADED", CaseStatus.GAP_FOUND.value):        "gap_analysis",
            ("DOCUMENTS_UPLOADED", CaseStatus.GAP_CLEARED.value):      "eligibility",
            ("ELIGIBILITY_REQUESTED", None):                           "eligibility",
            ("ELIGIBLE",           "APPROVED"):                         "packet_gen",
            ("GENERATE_PACKET_REQUESTED", CaseStatus.APPROVED.value):   "packet_gen",
            ("GENERATE_PACKET_REQUESTED", CaseStatus.GAP_CLEARED.value): "eligibility",
            ("PACKET_DONE",        CaseStatus.PACKET_READY.value):      "pending_approval",
            ("AUTO_SUBMIT",        CaseStatus.PACKET_READY.value):      "submit",
            ("STAFF_APPROVED",     CaseStatus.PENDING_APPROVAL.value):  "submit",
        }
        
        next_step = FALLBACK_MAP.get((event, db_status))
        if next_step is None:
            next_step = FALLBACK_MAP.get((event, None))
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
            logger.exception(f"[orchestrator] Step '{step}' raised: {e}")
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
        """
        Step 1 — Fetch and extract EHR data for the patient.
        
        OPTIMIZATION 3: EHR Smart Cache
        - First fetch: Query database (300-500ms)
        - Within 5 minutes: Return cached result (<1ms)
        - After 5 minutes: Fresh fetch again
        """
        from utils.cache_manager import general_cache
        
        # ──── CACHE CHECK (NEW - Optimization 3) ────
        EHR_CACHE_TTL_SECONDS = 300  # 5 minutes
        
        # Use CacheManager to check for fresh EHR fetch result
        # The key is case-specific to ensure isolation
        cache_key = f"ehr_fetch_done:{self.case_id}"
        if general_cache.get(cache_key, ttl=EHR_CACHE_TTL_SECONDS):
            logger.info(
                f"[orchestrator] EHR cache HIT for {self.case_id} (TTL={EHR_CACHE_TTL_SECONDS}s)"
            )
            return {"event": "EHR_FETCH_DONE"}
        
        # ──── FRESH EHR FETCH ────
        db_case.status = CaseStatus.EHR_FETCHING.value
        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_START", "RUNNING", "Fetching patient EHR data", db_session=db)
        # db.refresh(db_case) removed (wipes pending log entry)

        fill_extracted_data_from_ehr(db, patient_id=db_case.patient_id, case_id=db_case.case_id)

        db_case.status = CaseStatus.EHR_FETCHED.value
        db.add(db_case)
        db.commit()
        db.refresh(db_case)
        log_event(self.case_id, "ORCHESTRATOR", "EHR_FETCH_COMPLETE", "SUCCESS", "EHR data fetched", db_session=db)
        # Final refresh for this step is OK as we commit next or memory.save commits
        db.refresh(db_case)

        # Store in cache so we skip this for the next 5 minutes
        general_cache.set(cache_key, "DONE")

        return {"event": "EHR_FETCH_DONE"}

    async def _step_gap_analysis(self, db: Session, db_case, payload: dict) -> dict:
        """
        Step 2 — Run gap analysis LLM agent.
        
        OPTIMIZATION 4: Delta Gap Analysis
        - First run: Full LLM analysis (expensive)
        - Re-runs on file upload: Use lightweight delta version (fast)
        """
        # Removed broken inline import: from agents.gap_analysis_agent import run_gap_analysis_delta
        
        db_case.status = CaseStatus.GAP_ANALYSIS_RUNNING.value
        db.add(db_case)
        db.commit()

        # ──── OPTIMIZATION 4: Detect if we should use Delta Analysis ────
        trigger = getattr(self, '_current_trigger', None)  # Will be set by run() method
        use_delta = (
            trigger == "DOCUMENTS_UPLOADED" and 
            self.memory.succeeded("gap_analysis")  # Prior gap analysis exists
        )
        
        if use_delta:
            # Lightweight delta analysis - compare new files vs old gaps
            logger.info(f"[orchestrator] Using DELTA gap analysis for {self.case_id} (file upload trigger)")
            
            previous_gap = self.memory.get_last_result("gap_analysis")
            newly_uploaded = db_case.uploaded_files[-len(db_case.uploaded_files) + max(0, len(db_case.uploaded_files) - 5):] \
                           if db_case.uploaded_files else []
            
            agent_props = {
                "case_id": self.case_id,
                "previous_gap_result": previous_gap,
                "newly_uploaded_files": newly_uploaded,
                "payer_name": db_case.insurance_company,
                "ehr_data_cached": self.memory.get_cached_data("ehr_data"),  # Opt 7: Pass cached EHR
            }
            result = await run_gap_analysis_delta(agent_props)
            log_event(self.case_id, "ORCHESTRATOR", "USING_DELTA_ANALYSIS", "RUNNING", "Lightweight re-analysis for uploads", db_session=db)
            # db.refresh(db_case) removed (wipes pending log entry)
        
        else:
            # Full gap analysis (first run or other triggers)
            logger.info(f"[orchestrator] Using FULL gap analysis for {self.case_id}")
            
            agent_props = {
                "case_id": self.case_id,
                "patient_name": f"Patient {db_case.patient_id}",
                "pdf_path": payload.get("pdf_path"),
                "payer_name": db_case.insurance_company,
                "ehr_data_cached": self.memory.get_cached_data("ehr_data"),  # Opt 7: Pass cached EHR
            }
            result = await run_gap_analysis(agent_props)
        
        parsed = result.get("output") or {}

        # ── PERSISTENCE (Moved from agent to Orchestrator) ──
        summary = parsed.get("summary", {})
        db_case.gap_result = parsed

        # Determine next status based on LLM output
        new_status = parsed.get("status")
        if new_status == "INCOMPLETE":
            db_case.status = CaseStatus.GAP_ANALYSIS_FAILED.value
            event = "FAILED"
        elif new_status == CaseStatus.GAP_FOUND.value:
            db_case.status = CaseStatus.GAP_FOUND.value
            event = "GAP_FOUND"
        elif new_status == CaseStatus.GAP_CLEARED.value:
            db_case.status = CaseStatus.GAP_CLEARED.value
            event = "GAP_CLEARED"
        else:
            # Fallback: if no missing docs, it's cleared
            missing_docs = parsed.get("missing_documents")
            if isinstance(missing_docs, list) and len(missing_docs) == 0:
                db_case.status = CaseStatus.GAP_CLEARED.value
                event = "GAP_CLEARED"
            else:
                db_case.status = CaseStatus.GAP_FOUND.value
                event = "GAP_FOUND"

        db_case.total_required = summary.get("total_required")
        db_case.total_matched  = summary.get("total_matched")
        db_case.total_missing  = summary.get("total_missing")
        db_case.gap_percentage = summary.get("gap_percentage")

        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        # ── AUTO-SUMMARIZATION (NEW: Concurrent & Cached) ──
        if event == "GAP_CLEARED":
            log_event(
                self.case_id, 
                "ORCHESTRATOR", 
                "AUTO_SUMMARIZATION_STARTED", 
                "RUNNING", 
                "Summarizing uploaded patient files in parallel", 
                db_session=db
            )
            db.commit() # Force flush for frontend visibility
            
            try:
                # Runs concurrently and uses hash-based caching
                # No need to await if we want it truly backgrounded, 
                # but for Eligibility to use them, we should await.
                await summarize_case_documents(self.case_id)
                log_event(
                    self.case_id, 
                    "ORCHESTRATOR", 
                    "AUTO_SUMMARIZATION_COMPLETED", 
                    "SUCCESS", 
                    "Patient documents distilled and cached", 
                    db_session=db
                )
            except Exception as e:
                logger.error(f"[orchestrator] Auto-summarization failed: {e}")
                log_event(self.case_id, "ORCHESTRATOR", "AUTO_SUMMARIZATION_FAILED", "WARNING", str(e), db_session=db)

        # Final refresh for the step is fine
        db.refresh(db_case)

        return {"event": event, "gap_result": parsed}

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

        db_case.status = CaseStatus.ELIGIBILITY_RUNNING.value
        db.add(db_case)
        db.commit()

        loop = asyncio.get_event_loop()
        from functools import partial
        eligibility_func = partial(run_eligibility_check, db_session=db)
        
        result = await loop.run_in_executor(
            None,
            eligibility_func,
            {
                "case_id": self.case_id,
                "pdf_path": payload.get("pdf_path"),
                "payer_name": db_case.insurance_company,
                # Gap context is implicitly available via DB; we log it in memory
                "_gap_context": gap_output,
                "ehr_data_cached": self.memory.get_cached_data("ehr_data"),  # Opt 7: Pass cached EHR
            },
        )

        # ── PERSISTENCE (Moved from agent to Orchestrator) ──
        db_case.eligibility_result = result
        db_case.eligibility_verdict = result.get("verdict")
        db_case.confidence_score = result.get("probability_score", 0)
        
        if result.get("eligible"):
            db_case.status = CaseStatus.APPROVED.value
            event = "ELIGIBLE"
            if db_case.confidence_score >= 80:
                db_case.auto_submit_reason = f"AI Auto-Approved (Confidence: {db_case.confidence_score}%)"
            else:
                db_case.auto_submit_reason = f"Requires Manual Review (Confidence: {db_case.confidence_score}% < 80%)"
        else:
            db_case.status = CaseStatus.DENIED.value
            event = "NOT_ELIGIBLE"
            db_case.auto_submit_reason = f"AI Denied (Confidence: {db_case.confidence_score}%)"

        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        log_event(
            case_id=self.case_id,
            agent_name="ELIGIBILITY_AGENT",
            event="ELIGIBILITY_CHECK_COMPLETED",
            status=event,
            message=result.get("reason", "")[:200],
            db_session=db
        )
        db.commit()
        # db.refresh(db_case) removed (wipes pending log entry)

        return {"event": event, "eligibility_result": result}

    async def _step_packet_gen(self, db: Session, db_case, payload: dict) -> dict:
        """Step 4 — Generate the PA document package."""
        db_case.status = CaseStatus.PACKET_GENERATING.value
        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        log_event(self.case_id, "ORCHESTRATOR", "PACKET_GEN_START", "RUNNING", "Generating PA document package", db_session=db)
        db.commit()
        # db.refresh(db_case) removed (wipes pending log entry)

        loop = asyncio.get_event_loop()

        # Memory gives us access to both gap + eligibility outputs if needed by PA agent
        eligibility_output = self.memory.get_last_result("eligibility")
        if eligibility_output:
            logger.info(f"[orchestrator] PA gen has access to eligibility result from memory.")

        # Opt 7 & 10: Parallel Triple-Stream Generation (Async)
        content = await generate_pa_content(
            case_id=self.case_id,
            payer_name=db_case.insurance_company,
            cpt_code=db_case.cpt_code,
            pdf_path=payload.get("pdf_path"),
            ehr_data_cached=self.memory.get_cached_data("ehr_data"),
            db_session=db
        )

        # Collect uploaded file paths to attach to the PDF
        uploaded_paths = []
        if db_case.uploaded_files:
            for f in db_case.uploaded_files:
                path = f.get("file_path") or f.get("path")
                if path and os.path.exists(path):
                    uploaded_paths.append(path)

        log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_START", "RUNNING", "Building final PDF package", db_session=db)
        db.commit()
        # db.refresh(db_case) removed (wipes pending log entry)
        output_pdf = await loop.run_in_executor(
            None, generate_pa_pdf, self.case_id, content, uploaded_paths
        )

        logger.info(f"[orchestrator] PDF generated: {output_pdf}")
        log_event(self.case_id, "ORCHESTRATOR", "PDF_BUILD_COMPLETE", "SUCCESS", f"PDF: {os.path.basename(output_pdf)}", db_session=db)
        db.commit()
        # db.refresh(db_case) removed (wipes pending log entry)

        db_case.status = CaseStatus.PACKET_READY.value
        db.add(db_case)
        db.commit()

        # BRANCHING LOGIC: Decide if we should go to manual approval or auto-submit
        if db_case.confidence_score and db_case.confidence_score >= 80:
            logger.info(f"[orchestrator] HIGH CONFIDENCE ({db_case.confidence_score}%) - Triggering AUTO-SUBMIT for {self.case_id}")
            return {"event": "AUTO_SUBMIT", "pdf_path": output_pdf}
        
        return {"event": "PACKET_DONE", "pdf_path": output_pdf}

    async def _step_pending_approval(self, db: Session, db_case) -> dict:
        """Step 5 — Move case to PENDING_APPROVAL for staff review."""
        db_case.status = CaseStatus.PENDING_APPROVAL.value
        db.add(db_case)
        db.commit()
        db.refresh(db_case)
        log_event(self.case_id, "ORCHESTRATOR", "ORCHESTRATION_FLOW_COMPLETE", "SUCCESS", "Case ready for staff review", db_session=db)
        # Final refresh for this step is fine as it returns AWAITING_STAFF
        db.refresh(db_case)
        # Stop here — next trigger comes externally ("STAFF_APPROVED")
        return {"event": "AWAITING_STAFF"}

    async def _step_submit(self, db: Session, db_case) -> dict:
        log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_START", "RUNNING", "Submitting package to insurance portal", db_session=db)
        # db.refresh(db_case) removed (wipes pending log entry)
        
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
            db.refresh(db_case)
            
            log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_COMPLETE", "SUCCESS", "Package accepted by payer. Now tracking status.", db_session=db)
            # db.refresh(db_case) removed (wipes pending log entry)
            
        except Exception as e:
            logger.error(f"[orchestrator] Submission failed: {e}")
            log_event(self.case_id, "ORCHESTRATOR", "SUBMISSION_FAILED", "FAILED", str(e), db_session=db)
            # db.refresh(db_case) removed (wipes pending log entry)
            db_case.status = CaseStatus.FAILED.value
            db.add(db_case)
            db.commit()
            return {"event": "FAILED", "error": str(e)}

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
        log_event(self.case_id, "ORCHESTRATOR", "RETRY_STARTED", "RUNNING", "Retrying last failed step", db_session=db)
        # Ensure retry log is anchored
        db.commit()
        db.refresh(db_case)

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

        # If retry succeeded, continue deterministically from resulting event
        if event != "FAILED":
            db.refresh(db_case)
            next_step = self._resolve_next_step(event, db_case.status)
            continued = 0
            while next_step:
                continued += 1
                if continued > self._max_steps:
                    logger.error(
                        f"[orchestrator] Safety stop during retry continuation for {self.case_id}: exceeded max steps ({self._max_steps})."
                    )
                    break

                if self.memory.succeeded(next_step):
                    logger.info(f"[orchestrator] Retry continuation skipping '{next_step}' — already succeeded.")
                    prior_result = self.memory.get_last_result(next_step)
                    prior_event = prior_result.get("event", "") if prior_result else ""
                    db.refresh(db_case)
                    next_step = self._resolve_next_step(prior_event, db_case.status)
                    continue

                follow_result = await self._execute_step(next_step, db, db_case, payload)
                follow_event = follow_result.get("event", "FAILED")

                self.memory.record(
                    step=next_step,
                    inputs={"case_id": self.case_id, "retry_chain": True},
                    result=follow_result,
                    status="SUCCESS" if follow_event != "FAILED" else "FAILED",
                )
                self.memory.save(db)

                if follow_event == "FAILED":
                    logger.error(f"[orchestrator] Retry continuation step '{next_step}' failed. Halting.")
                    break

                db.refresh(db_case)
                next_step = self._resolve_next_step(follow_event, db_case.status)
