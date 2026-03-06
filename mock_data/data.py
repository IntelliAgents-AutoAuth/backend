from constants.roles import UserRole

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

MOCK_CASES = [
    {
        "case_id": 1,
        "patient_name": "John Doe",
        "procedure": "Appendectomy",
        "status": "active",
        "assigned_to": "sai@example.com",
    },
    {
        "case_id": 2,
        "patient_name": "Jane Smith",
        "procedure": "Knee Replacement",
        "status": "closed",
        "assigned_to": "sai@example.com",
    },
    {
        "case_id": 3,
        "patient_name": "Alice Johnson",
        "procedure": "Hip Surgery",
        "status": "active",
        "assigned_to": "ramesh@example.com",
    },
    {
        "case_id": 4,
        "patient_name": "Bob Williams",
        "procedure": "Cardiac Bypass",
        "status": "active",
        "assigned_to": "admin@example.com",
    },
]
