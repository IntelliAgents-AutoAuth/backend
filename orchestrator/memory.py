"""
OrchestratorMemory — Hybrid Persistence & State Management
==========================================================

The OrchestratorMemory class provides a specialized persistence layer for the 
CaseOrchestrator. It ensures that every action taken by an AI agent is 
recorded, searchable, and reusable by downstream agents.

Architecture:
-------------
1. **L1 Cache (RAM)**: Uses 'general_cache' (shared memory) for sub-millisecond 
   access to recent case history within the current process.
2. **L2 Cache (Database)**: Persists the structured history into the 
   `cases.audit_log` JSON column in the SQL database.
3. **LangChain Integration**: Inherits from 'BaseChatMessageHistory', allowing 
   the orchestrator memory to be dropped directly into LangChain workflows.

Key Benefits:
-------------
- **No Redundancy**: The `already_ran()` and `succeeded()` checks prevent 
  paying for the same LLM call twice.
- **Context Passing**: Upstream results (e.g., Gap Analysis JSON) are stored 
  and passed directly to downstream agents (e.g., Eligibility) without 
  expensive re-computation.
- **Auditability**: Every step, its inputs, raw LLM outputs, and final 
  verdicts are logged for human review and debugging.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from db import get_case

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HYBRID CACHE (L1 RAM + L2 DB)
# ─────────────────────────────────────────────────────────────────────────────

from utils.cache_manager import general_cache

class OrchestratorMemory(BaseChatMessageHistory):
    """
    Manages the 'Short-term' and 'Long-term' memory for a specific case.

    This class bridges the gap between fast in-memory execution and permanent 
    database storage. It is designed to be 'Schema-less' by using a JSONB-style 
    audit log, making it highly flexible as new agents or steps are added.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        self._log: list[dict] = []
        # _data_cache no longer needed as a self-instance; we use general_cache

    # ─────────────────────────────────────────
    # LANGCHAIN PROXY (read-only for messages)
    # ─────────────────────────────────────────

    @property
    def messages(self) -> list[BaseMessage]:
        """
        Map our internal audit_log dicts to LangChain BaseMessage objects.
        Handles legacy entries (which use 'event') gracefully.
        """
        msgs = []
        for entry in self._log:
            step = entry.get("step") or entry.get("event") or "unknown"
            ts = entry.get("timestamp")
            status = entry.get("status")

            # Inputs -> HumanMessage
            inputs = entry.get("inputs") or {}
            msgs.append(
                HumanMessage(
                    content=str(inputs),
                    additional_kwargs={
                        "step": step,
                        "type": "input",
                        "timestamp": ts,
                        "status": status,
                    },
                )
            )
            # Result -> AIMessage
            result = entry.get("result") or entry.get("metadata") or {}
            msgs.append(
                AIMessage(
                    content=str(result),
                    additional_kwargs={
                        "step": step,
                        "type": "output",
                        "timestamp": ts,
                        "status": status,
                    },
                )
            )
        return msgs

    def add_messages(self, messages: list[BaseMessage]) -> None:
        """
        Note: The orchestrator uses record() for structured logging.
        This method is provided for standard LangChain compatibility.
        """
        for msg in messages:
            step = msg.additional_kwargs.get("step", "unspecified")
            status = msg.additional_kwargs.get("status", "SUCCESS")
            # We treat Human as input and AI as result
            if isinstance(msg, HumanMessage):
                self.record(step, inputs=eval(msg.content) if "{" in msg.content else msg.content, result={}, status=status)
            elif isinstance(msg, AIMessage):
                # Update last entry if it's the same step
                if self._log and self._log[-1]["step"] == step:
                     self._log[-1]["result"] = eval(msg.content) if "{" in msg.content else msg.content
                else:
                     self.record(step, inputs={}, result=eval(msg.content) if "{" in msg.content else msg.content, status=status)

    def clear(self) -> None:
        """Clear both L1 RAM and prepare for L2 purge."""
        self._log = []
        general_cache.delete_by_case(self.case_id, "memory")
        general_cache.delete_by_case(self.case_id, "data")
        logger.info(f"[memory] Cleared memory for case {self.case_id}")

    # ─────────────────────────────────────────
    # DATA CACHING (for arbitrary objects like EHR data)
    # ─────────────────────────────────────────

    def set_cached_data(self, key: str, value: Any) -> None:
        """Store arbitrary data in L1 cache (e.g., EHR data for multi-agent access)."""
        # Store using the centralized namespaced helper
        general_cache.set_by_case(self.case_id, f"data:{key}", value)
        logger.info(f"[memory] Cached data for key='{key}' in case {self.case_id}")

    def get_cached_data(self, key: str) -> Any | None:
        """Retrieve cached data (e.g., EHR data) from L1 cache."""
        value = general_cache.get_by_case(self.case_id, f"data:{key}")
        if value is not None:
            logger.info(f"[memory] Cache HIT for key='{key}' in case {self.case_id}")
        else:
            logger.info(f"[memory] Cache MISS for key='{key}' in case {self.case_id}")
        return value

    # ─────────────────────────────────────────
    # PERSISTENCE (L1/L2 logic)
    # ─────────────────────────────────────────

    def load(self, db) -> None:
        """
        Loads the case history from the most efficient source available.

        Priority:
        1. **L1 RAM**: If the case was recently processed in this process, 
           load from the shared memory cache (fastest).
        2. **L2 DB**: If not in RAM, fetch the 'audit_log' from the database 
           and hydrate the RAM cache for subsequent calls.
        """
        # 1. Try RAM Cache (L1) via centralized namespacing
        cached_log = general_cache.get_by_case(self.case_id, "memory")
        if cached_log is not None:
            self._log = cached_log
            logger.info(f"[memory] L1 CACHE HIT: Loaded {len(self._log)} entries for {self.case_id}")
            return

        # 2. Try DB (L2)
        db_case = get_case(db, case_id=self.case_id)
        if db_case and db_case.audit_log:
            self._log = list(db_case.audit_log)
        else:
            self._log = []

        # Update RAM Cache for next time
        general_cache.set_by_case(self.case_id, "memory", self._log)
        logger.info(
            f"[memory] L1 CACHE MISS (L2 Loaded): {len(self._log)} entries for {self.case_id}"
        )

    def save(self, db) -> None:
        """
        Synchronizes the in-memory state with the permanent database.

        Safety Logic:
        It performs a 'Smart Merge' with the existing database audit log. 
        This prevents the orchestrator from overwriting logs generated by 
        other system events (like manual status changes or background tasks).
        """
        # Update L1 RAM via centralized namespacing
        general_cache.set_by_case(self.case_id, "memory", self._log)

        # Update L2 DB
        # IMPORTANT: Merge with existing audit_log instead of replacing it
        # This preserves event-based logs from agent_logger while adding orchestrator steps
        db_case = get_case(db, case_id=self.case_id)
        if db_case:
            # Get existing audit log (contains event-based entries from agent_logger)
            existing_audit_log = db_case.audit_log or []
            
            # Extract step names we're recording (to avoid duplicating old versions)
            recorded_steps = {entry.get("step") for entry in self._log if entry.get("step")}
            
            # Filter existing log: keep events and non-conflicting steps
            merged_log = []
            for entry in existing_audit_log:
                # Keep all event-based entries (from agent_logger)
                if "event" in entry and "agent_name" in entry:
                    merged_log.append(entry)
                # Keep steps we're not re-recording
                elif entry.get("step") not in recorded_steps:
                    merged_log.append(entry)
            
            # Add new orchestrator step entries
            merged_log.extend(self._log)
            
            # Sort by timestamp to maintain chronological order
            merged_log.sort(key=lambda x: x.get("timestamp", ""), reverse=False)
            
            db_case.audit_log = merged_log
            db.add(db_case)
            db.commit()
            logger.info(
                f"[memory] L1 and L2 synchronized for case {self.case_id} "
                f"(merged: {len(existing_audit_log)} existing + {len(self._log)} steps = {len(merged_log)} total)"
            )


    # ─────────────────────────────────────────
    # RECORDING
    # ─────────────────────────────────────────

    def record(
        self,
        step: str,
        inputs: dict,
        result: Any,
        status: str = "SUCCESS",
    ) -> None:
        """Record one execution and update L1 cache immediately."""
        entry = {
            "step": step,
            "inputs": inputs,
            "result": result,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._log.append(entry)
        
        # Immediate L1 Cache update via centralized namespacing
        general_cache.set_by_case(self.case_id, "memory", self._log)
        
        logger.info(f"[memory] Recorded step '{step}' → {status}")

    # ─────────────────────────────────────────
    # QUERYING
    # ─────────────────────────────────────────

    def already_ran(self, step: str) -> bool:
        """Check if step ran (uses L1 in-memory log, resilient to legacy data)."""
        return any((e.get("step") or e.get("event")) == step for e in self._log)

    def succeeded(self, step: str) -> bool:
        """Check if step succeeded (uses L1 in-memory log, resilient to legacy data)."""
        return any(
            ((e.get("step") or e.get("event")) == step) and e.get("status") == "SUCCESS"
            for e in self._log
        )

    def get_last_result(self, step: str) -> dict | None:
        """Return result from L1 in-memory log (resilient to legacy data)."""
        for entry in reversed(self._log):
            if (entry.get("step") or entry.get("event")) == step:
                return entry.get("result") or entry.get("metadata")
        return None

    def get_timestamp(self, step: str) -> datetime | None:
        """
        Return the timestamp of the last execution of a step.
        Used for cache freshness checks (e.g., EHR fetch within 5 minutes).
        
        Returns:
            datetime object or None if step not found
        """
        for entry in reversed(self._log):
            if (entry.get("step") or entry.get("event")) == step:
                ts_str = entry.get("timestamp")
                if ts_str:
                    try:
                        return datetime.fromisoformat(ts_str)
                    except Exception:
                        return None
        return None

    def get_history(self) -> list[dict]:
        """Return history from L1 in-memory log."""
        return list(self._log)

    def summary(self) -> str:
        """Human-readable summary from L1 in-memory log."""
        if not self._log:
            return "No steps recorded yet."
        parts = [f"{e['step']}({e['status']})" for e in self._log]
        return " -> ".join(parts)
