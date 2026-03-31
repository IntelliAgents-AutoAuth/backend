from constants import UserRole

MOCK_USERS = {
    "pa_coordinator_1": {
        "email": "sai@example.com",
        "password": "test123",
        "role": UserRole.PA_COORDINATOR,
        "name": "Sai"
    },
    "physician_1": {
        "email": "ramesh@example.com",
        "password": "test123",
        "role": UserRole.PHYSICIAN,
        "name": "Dr. Ramesh Kumar"
    },
    "admin_1": {
        "email": "admin@example.com",
        "password": "admin123",
        "role": UserRole.ADMIN,
        "name": "Admin User"
    }
}

