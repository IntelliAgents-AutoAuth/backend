from db.session import SessionLocal
from crud import crud_case
import json

db = SessionLocal()
case_id = "PA-20260317-00013"
db_case = crud_case.get_case(db, case_id=case_id)
if db_case:
    print(f"Status: {db_case.status}")
    print("Timeline:")
    for entry in db_case.audit_log:
        print(f"  {entry.get('event')}: {entry.get('status')} - {entry.get('message')}")
else:
    print(f"Case {case_id} not found")
db.close()
