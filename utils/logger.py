"""
Unified Logging and Observability Module
Consolidates terminal, file, and database audit logging + Arize Phoenix setup.
"""

import os
import sys
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from sqlalchemy.orm.attributes import flag_modified

# Add backend to sys.path if needed
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from constants import LogEvent
from db import SessionLocal
from db import get_case

# ─────────────────────────────────────────────────────────────────────────────
# 1. STANDALONE LOGGER SETUP (Console + File)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 1. STANDALONE LOGGER SETUP (Console + File)
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(backend_dir, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "pa_system.log")

_logger = logging.getLogger("pa_system")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    # Formatter optimized for both JSON and simple strings
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    
    # File Handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

# ─────────────────────────────────────────────────────────────────────────────
# 2. CORE UNIFIED LOGGING FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def log_event(
    event: str,
    agent_name: str,
    case_id: Optional[str] = "N/A",
    status: Optional[str] = "INFO",
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db_session: Any = None,
    duration_ms: Optional[int] = None
) -> Dict[str, Any]:
    """
    Unified entry point for ALL logging in the system.
    1. Logs a structured message to Terminal/File.
    2. Persists to Database Audit Log if case_id and db_session are provided.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Check if event is from LogEvent enum
    event_val = event.value if hasattr(event, 'value') else str(event)
    
    # Build internal log dict
    log_entry = {
        "timestamp": timestamp,
        "event": event_val,
        "agent_name": agent_name,
        "case_id": case_id,
        "status": status,
        "message": message or "",
        "metadata": metadata or {},
        "duration_ms": duration_ms
    }

    # 1. LOG TO TERMINAL / FILE (JSON-like but readable)
    log_msg = f"[{agent_name}] {event_val} | Case: {case_id} | {message or ''}"
    if metadata:
        log_msg += f" | Details: {json.dumps(metadata)}"
        
    s_upper = status.upper() if status else "INFO"
    try:
        if s_upper == "DEBUG": _logger.debug(log_msg)
        elif s_upper == "WARNING": _logger.warning(log_msg)
        elif s_upper == "ERROR": _logger.error(log_msg)
        elif s_upper == "FAILED": _logger.error(log_msg)
        elif s_upper == "SUCCESS": _logger.info(log_msg)
        else: _logger.info(log_msg)
    except Exception as e:
        # We don't want a terminal/encoding error to crash the whole application flow!
        # Just print a minimal fallback or ignore.
        print(f"[logger] LOGGING FAIL (potential Unicode error): {e}")

    # 2. LOG TO DATABASE (Audit Log in Case model)
    if case_id and case_id != "N/A":
        _persist_to_db(case_id, log_entry, db_session)

    return log_entry

def _persist_to_db(case_id: str, entry: dict, db_session=None):
    """Internal helper to save logs to the audit_log JSON array in SQLite."""
    db = db_session
    close_db = False
    if not db:
        db = SessionLocal()
        close_db = True
    
    try:
        db_case = get_case(db, case_id=case_id)
        if db_case:
            current_logs = list(db_case.audit_log or [])
            current_logs.append(entry)
            db_case.audit_log = current_logs
            db.add(db_case)
            
            if close_db:
                db.commit()
            else:
                flag_modified(db_case, 'audit_log')
    except Exception as e:
        _logger.error(f"Failed to persist audit log to DB for {case_id}: {e}")
        if close_db: db.rollback()
    finally:
        if close_db: db.close()

# ─────────────────────────────────────────────────────────────────────────────
# 3. AUTH & CONVENIENCE WRAPPERS
# ─────────────────────────────────────────────────────────────────────────────

def log_login_success(username: str):
    return log_event("LOGIN_SUCCESS", agent_name="AuthService", metadata={"username": username})

def log_login_failed(username: str, reason: str = "Invalid credentials"):
    return log_event("LOGIN_FAILED", agent_name="AuthService", status="WARNING", metadata={"username": username, "reason": reason})

def log_logout(username: str):
    return log_event("LOGOUT", agent_name="AuthService", metadata={"username": username})

def log_token_expired(username: str):
    return log_event("TOKEN_EXPIRED", agent_name="AuthService", status="WARNING", metadata={"username": username})

# ─────────────────────────────────────────────────────────────────────────────
# 4. OBSERVABILITY (Arize Phoenix) SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_observability():
    """
    Centralized Arize Phoenix / OpenInference instrumentation.
    Includes Windows-specific fix for phoenix.db PermissionErrors.
    """
    try:
        import phoenix as px
        from phoenix.otel import register
        from openinference.instrumentation.langchain import LangChainInstrumentor

        if not px.active_session():
            _logger.info("Launching Arize Phoenix dashboard...")
            session = px.launch_app()
            _logger.info(f"Phoenix dashboard active: {session.url}")
        
        # Use simple register() - it will pick up PHOENIX_WORKING_DIR if needed
        # We wrap in try block to prevent crash if already registered
        try:
            tracer_provider = register()
            LangChainInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
            _logger.info("LangChain instrumentation active globally.")
        except Exception as e:
            _logger.warning(f"Telemetry registration skipped (likely already active): {e}")

    except ImportError:
        _logger.warning("Arize Phoenix not installed, observability skipped.")
    except Exception as e:
        _logger.error(f"Failed to initialize observability: {e}")
