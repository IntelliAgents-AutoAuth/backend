import logging
from datetime import datetime, timezone
from db.session import SessionLocal
from crud import crud_case
from sqlalchemy import text
import time

logger = logging.getLogger(__name__)

def log_event(
    case_id:     str,
    agent_name:  str,
    event:       str,
    status:      str,
    message:     str  = None,
    metadata:    dict = None,
    duration_ms: int  = None,
    db_session = None  # Optional: pass in existing session to reuse transaction
):
    """
    Appends one log entry to cases.audit_log JSON array.
    No new table needed — uses existing cases table.
    If db_session is provided, uses that session (for same-transaction logging).
    Otherwise creates a new session (for standalone logging).
    """
    
    # Use provided session or create new one
    db = db_session
    close_db = False
    if not db:
        db = SessionLocal()
        close_db = True
    
    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if not db_case:
            logger.warning(f"[agent_logger] Case {case_id} not found")
            return False

        # Get existing logs or empty list
        # We need to create a new list object to ensure SQLAlchemy detects the change
        current_logs = db_case.audit_log or []
        logs = list(current_logs)

        # Append new entry
        new_entry = {
            "event":       event,
            "agent_name":  agent_name,
            "status":      status,
            "message":     message,
            "metadata":    metadata or {},
            "duration_ms": duration_ms,
            "timestamp":   datetime.now(timezone.utc).isoformat()
        }
        logs.append(new_entry)

        # Save back
        db_case.audit_log = logs
        db.add(db_case)
        
        # Only commit if we created the session (don't commit if using existing session)
        if close_db:
            db.commit()
        else:
            # If using existing session, just mark modified and let caller commit
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(db_case, 'audit_log')
        
        return True

    except Exception as e:
        logger.error(f"[agent_logger] Failed to log event for {case_id}: {e}")
        if close_db:
            db.rollback()
        return False
    finally:
        if close_db:
            db.close()
