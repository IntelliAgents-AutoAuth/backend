from sqlalchemy.orm import Session
from models.extracted_data import ExtractedData
from schemas.extracted_data import ExtractedDataCreate, ExtractedDataUpdate

def get_extracted_data(db: Session, case_id: str):
    return db.query(ExtractedData).filter(ExtractedData.case_id == case_id).first()

def create_extracted_data(db: Session, obj_in: ExtractedDataCreate):
    db_obj = ExtractedData(**obj_in.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def update_extracted_data(db: Session, db_obj: ExtractedData, obj_in: ExtractedDataUpdate):
    obj_data = db_obj.to_dict() if hasattr(db_obj, 'to_dict') else {c.name: getattr(db_obj, c.name) for c in db_obj.__table__.columns}
    update_data = obj_in.model_dump(exclude_unset=True)
    for field in obj_data:
        if field in update_data:
            setattr(db_obj, field, update_data[field])
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
