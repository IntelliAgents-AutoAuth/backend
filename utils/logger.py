"""
Central Logging Module
Author: Nikhil
Description: Handles logging for Authentication and Case Creation only.
             All log entries include timestamp, case_id, event_name, agent_name.
"""

import json
import logging
import os
from datetime import datetime, timezone
from constants.logging import LogEvent




# ──────────────────────────────────────────────
# Logger Setup (console + file)
# ──────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "pa_system.log")

_logger = logging.getLogger("pa_system")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    console_handler = logging.StreamHandler()
    file_handler    = logging.FileHandler(LOG_FILE)
    formatter       = logging.Formatter("%(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    _logger.addHandler(file_handler)


# ──────────────────────────────────────────────
# Core Log Function
# ──────────────────────────────────────────────
def log_event(
    event: LogEvent,
    agent_name: str,
    case_id: str = None,
    details: dict = None,
    level: str = "INFO"
) -> dict:
    """
    Creates a structured log entry and writes to console + file.

    Args:
        event      : One of the LogEvent enum values
        agent_name : Service generating the event (e.g. AuthService)
        case_id    : Optional — not available at login time
        details    : Optional extra context
        level      : INFO, WARNING, ERROR, DEBUG

    Returns:
        The log entry as a dict
    """
    entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "event":      event.value,
        "agent_name": agent_name,
        "case_id":    case_id or "N/A",
        "details":    details or {}
    }

    message = json.dumps(entry)

    level = level.upper()
    if level == "DEBUG":
        _logger.debug(message)
    elif level == "WARNING":
        _logger.warning(message)
    elif level == "ERROR":
        _logger.error(message)
    else:
        _logger.info(message)

    return entry


# ──────────────────────────────────────────────
# Auth Wrappers
# ──────────────────────────────────────────────
def log_login_success(username: str):
    return log_event(LogEvent.LOGIN_SUCCESS, agent_name="AuthService Auth",
                     details={"username": username})

def log_login_failed(username: str, reason: str = "Invalid credentials"):
    return log_event(LogEvent.LOGIN_FAILED, agent_name="AuthService Auth",
                     details={"username": username, "reason": reason}, level="WARNING")

def log_logout(username: str):
    return log_event(LogEvent.LOGOUT, agent_name="AuthService Auth",
                     details={"username": username})

def log_token_expired(username: str):
    return log_event(LogEvent.TOKEN_EXPIRED, agent_name="AuthService Auth",
                     details={"username": username}, level="WARNING")


