import os
import sys

# Add the backend directory to sys.path
backend_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(backend_path)

try:
    from services.extraction_service import fill_extracted_data_from_ehr
    print("Successfully imported fill_extracted_data_from_ehr")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

# We can't easily call it without a DB session, but we can check the bytecode/attrs
print(f"Function name: {fill_extracted_data_from_ehr.__name__}")
print(f"Function module: {fill_extracted_data_from_ehr.__module__}")
