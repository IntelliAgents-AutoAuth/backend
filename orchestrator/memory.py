"""
OrchestratorMemory
==================
Tracks every agent call made by the orchestrator for a given case:
  - Which step/agent was called
  - What inputs were sent
  - What result came back
  - Whether it succeeded or failed
  - When it happened

Stored in the existing `cases.audit_log` JSON column — no schema migration needed.

Usage in orchestrator:
    memory = OrchestratorMemory(case_id)
    memory.load(db)                          # load prior history from DB

    # Before calling an agent:
    if memory.already_ran("gap_analysis"):
        result = memory.get_last_result("gap_analysis")
    else:
        result = await run_gap_analysis(inputs)
        memory.record("gap_analysis", inputs, result, "SUCCESS")

    memory.save(db)                          # persist back to DB
"""

import logging
from datetime import datetime, timezone
from typing import Any
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from crud import crud_case

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HYBRID CACHE (L1 RAM + L2 DB)
# ─────────────────────────────────────────────────────────────────────────────

# Global L1 Cache in RAM
# Key: case_id, Value: list of log entries
_MEMORY_CACHE: dict[str, list[dict]] = {}


class OrchestratorMemory(BaseChatMessageHistory):
    """
    Hybrid RAM/DB memory for Orchestration.

    Inherits from LangChain's BaseChatMessageHistory to allow use within
    LangChain chains, while maintaining our structured audit_log in SQL.

    L1: RAM (Process-level dictionary)
    L2: DB (cases.audit_log column)
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        self._log: list[dict] = []
        self._data_cache: dict[str, Any] = {}  # L1 in-memory cache for arbitrary data (e.g., EHR)

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
        self._data_cache = {}
        if self.case_id in _MEMORY_CACHE:
            del _MEMORY_CACHE[self.case_id]
        logger.info(f"[memory] Cleared memory for case {self.case_id}")

    # ─────────────────────────────────────────
    # DATA CACHING (for arbitrary objects like EHR data)
    # ─────────────────────────────────────────

    def set_cached_data(self, key: str, value: Any) -> None:
        """Store arbitrary data in L1 cache (e.g., EHR data for multi-agent access)."""
        self._data_cache[key] = value
        logger.info(f"[memory] Cached data for key='{key}' in case {self.case_id}")

    def get_cached_data(self, key: str) -> Any | None:
        """Retrieve cached data (e.g., EHR data) from L1 cache."""
        value = self._data_cache.get(key)
        if value is not None:
            logger.info(f"[memory] Cache HIT for key='{key}' in case {self.case_id}")
        else:
            logger.info(f"[memory] Cache MISS for key='{key}' in case {self.case_id}")
        return value

    # ─────────────────────────────────────────
    # PERSISTENCE (L1/L2 logic)
    # ─────────────────────────────────────────

    def load(self, db) -> None:
        """Load history: RAM Cache first (L1), then DB Fallback (L2)."""
        # 1. Try RAM Cache (L1)
        if self.case_id in _MEMORY_CACHE:
            self._log = _MEMORY_CACHE[self.case_id]
            logger.info(f"[memory] L1 CACHE HIT: Loaded {len(self._log)} entries for {self.case_id}")
            return

        # 2. Try DB (L2)
        db_case = crud_case.get_case(db, case_id=self.case_id)
        if db_case and db_case.audit_log:
            self._log = list(db_case.audit_log)
        else:
            self._log = []

        # Update RAM Cache for next time
        _MEMORY_CACHE[self.case_id] = self._log
        logger.info(
            f"[memory] L1 CACHE MISS (L2 Loaded): {len(self._log)} entries for {self.case_id}"
        )

    def save(self, db) -> None:
        """Save history: Sync L1 RAM and flush to L2 DB."""
        # Update L1 RAM
        _MEMORY_CACHE[self.case_id] = self._log

        # Update L2 DB
        db_case = crud_case.get_case(db, case_id=self.case_id)
        if db_case:
            db_case.audit_log = list(self._log)
            db.add(db_case)
            db.commit()
            logger.info(
                f"[memory] L1 and L2 synchronized for case {self.case_id}"
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
        
        # Immediate L1 Cache update
        _MEMORY_CACHE[self.case_id] = self._log
        
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
