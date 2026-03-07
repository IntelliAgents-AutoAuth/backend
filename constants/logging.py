from enum import Enum

class LogEvent(str, Enum):
    # Authentication
    LOGIN_SUCCESS      = "login_success"
    LOGIN_FAILED       = "login_failed"
    LOGOUT             = "logout"
    TOKEN_EXPIRED      = "token_expired"
