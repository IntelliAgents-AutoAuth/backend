from datetime import datetime, timezone
from db.session import SessionLocal
from crud import crud_case
from sqlalchemy import text

def log_event(
    case_id:     str,
    agent_name:  str,
    event:       str,
    status:      str,
    message:     str  = None,
    metadata:    dict = None,
    duration_ms: int  = None
):
    """
    Appends one log entry to cases.audit_log JSON array.
    No new table needed — uses existing cases table.
    """
    db = SessionLocal()
    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if not db_case:
            print(f"[agent_logger] Case {case_id} not found")
            return

        # Get existing logs or empty list
        # We need to create a new list object to ensure SQLAlchemy detects the change
        current_logs = db_case.audit_log or []
        logs = list(current_logs)

        # Append new entry
        logs.append({
            "event":       event,
            "agent_name":  agent_name,
            "status":      status,
            "message":     message,
            "metadata":    metadata or {},
            "duration_ms": duration_ms,
            "timestamp":   datetime.now(timezone.utc).isoformat()
        })

        # Save back
        db_case.audit_log = logs
        db.add(db_case)
        db.commit()

        print(f"[audit_log] {case_id} | {event} | {status}")

    except Exception as e:
        print(f"[agent_logger] Failed to log event for {case_id}: {e}")
        db.rollback()
    finally:
        db.close()
