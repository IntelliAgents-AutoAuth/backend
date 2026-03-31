from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
import os
import shutil
from datetime import datetime
import json

router = APIRouter(prefix="/payer", tags=["payer"])

@router.post("/submissions")
async def receive_submission(
    case_id: str = Form(...),
    patient_name: str = Form(...),
    cpt_code: str = Form(...),
    diagnosis: str = Form(None),
    package_pdf: UploadFile = File(...)
):
    """
    Simulated Provider/Payer endpoint to receive incoming Prior Auth packets.
    Saves the incoming packet to a "provider_inbox" directory.
    """
    try:
        # 1. Ensure provider inbox directory exists
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        inbox_dir = os.path.join(backend_dir, "provider_inbox", case_id)
        os.makedirs(inbox_dir, exist_ok=True)
        
        # 2. Save the PDF
        file_path = os.path.join(inbox_dir, package_pdf.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(package_pdf.file, buffer)
            
        # 3. Save submission metadata for the provider dashboard to read later
        metadata_path = os.path.join(inbox_dir, "metadata.json")
        metadata = {
            "case_id": case_id,
            "patient_name": patient_name,
            "cpt_code": cpt_code,
            "diagnosis": diagnosis,
            "submission_time": datetime.now().isoformat(),
            "status": "PENDING_REVIEW", # Initial status on the provider side
            "pdf_file": package_pdf.filename
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=4)
            
        print(f"[payer_endpoint] Received submission for case {case_id}")
        return {"status": "SUCCESS", "message": "Packet received successfully on provider side."}
        
    except Exception as e:
        print(f"[payer_endpoint] Error handling submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Provider endpoint failed: {str(e)}"
        )
