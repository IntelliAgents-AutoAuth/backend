import os
import sys
import json
import asyncio
import sqlite3
import argparse
from pathlib import Path
from typing import Optional

# Setup backend path
current_file_path = os.path.abspath(__file__)
scripts_dir = os.path.dirname(current_file_path)
backend_dir = os.path.dirname(scripts_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

os.chdir(backend_dir)

# Common imports
from pypdf import PdfReader
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from db import SessionLocal, engine
from db import Base
from utils.llm_util import RobustLLM
from prompts import get_policy_extraction_prompt, get_pdf_summarization_prompt
from utils.cache_manager import rules_cache, general_cache
from tools.rag import get_policy_vectorstore, get_embeddings
from langchain_community.vectorstores import Chroma

# --- Phoenix Instrumentation ---
def setup_phoenix():
    try:
        from phoenix.otel import register
        from openinference.instrumentation.langchain import LangChainInstrumentor
        tracer_provider = register(endpoint="http://127.0.0.1:6006/v1/traces")
        LangChainInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
        print("[observability] LangChain instrumentation connected to Phoenix at :6006")
    except Exception as e:
        pass # Ignore if Phoenix not running

# ─────────────────────────────────────────────────────────────────────────────
# DB MIGRATION & UTILS
# ─────────────────────────────────────────────────────────────────────────────

def migrate_db():
    """Add missing columns to existing database."""
    db_path = os.path.join(backend_dir, "data", "autoauth.db")
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        print(f"Checking database schema for: {db_path}")
        
        cols_to_add = [
            ("confidence_score", "FLOAT"),
            ("auto_submit_reason", "VARCHAR(255)")
        ]
        
        for col_name, col_type in cols_to_add:
            try:
                cursor.execute(f"ALTER TABLE cases ADD COLUMN {col_name} {col_type}")
                print(f"✅ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    print(f"⚠️ Column error ({col_name}): {e}")

        conn.commit()
        conn.close()
        print("🚀 Database schema check complete!")
    except Exception as e:
        print(f"❌ Error updating database: {e}")

def recreate_ehr_table():
    """Drop and recreate EHR-related tables."""
    with engine.connect() as conn:
        conn.execute(text('DROP TABLE IF EXISTS "case"'))
        conn.execute(text('DROP TABLE IF EXISTS "cases"'))
        conn.execute(text('DROP TABLE IF EXISTS "ehrs"'))
        conn.commit()
        print("Dropped old case/cases/ehrs tables")

    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    print("DB tables now:", insp.get_table_names())

def seed_db():
    """Seed DB with mock users and clinical records."""
    from models.user import User
    from models.ehr_records import EHR
    from mock_data.data import MOCK_USERS
    from mock_data.ehr_records import MOCK_EHR_RECORDS
    from core.security import get_password_hash

    db = SessionLocal()
    try:
        # Seed users
        for user_data in MOCK_USERS.values():
            user = db.query(User).filter(User.email == user_data["email"]).first()
            if not user:
                db_obj = User(
                    email=user_data["email"],
                    hashed_password=get_password_hash(user_data["password"]),
                    full_name=user_data.get("full_name") or user_data.get("name"),
                    role=user_data["role"],
                    is_active=True
                )
                db.add(db_obj)
        db.commit()
        print("[OK] Seeded mock users.")

        # Seed EHR
        for record_data in MOCK_EHR_RECORDS:
            db_record = db.query(EHR).filter(EHR.patient_id == record_data["patient_id"]).first()
            if not db_record:
                db.add(EHR(**record_data))
            else:
                for key, value in record_data.items():
                    setattr(db_record, key, value)
        db.commit()
        print("[OK] Seeded EHR records.")
    finally:
        db.close()

# ─────────────────────────────────────────────────────────────────────────────
# POLICY INGESTION logic
# ─────────────────────────────────────────────────────────────────────────────

PAYER_DIRECTORY_MAP = {
    "aetna": "Aetna", "bcbs": "BCBS", "cigna": "Cigna", 
    "cms": "CMS", "humana": "Humana", "united-healthcare": "United Healthcare"
}

def extract_policy_details_sync(pdf_path, llm, prompt_template):
    try:
        reader = PdfReader(pdf_path)
        text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
        if not text.strip(): return {"error": "No text found"}
        response = llm.invoke(prompt_template.invoke({"input": text}))
        content = response.content.strip().replace("```json", "").replace("```", "").strip()
        return {"file": os.path.basename(pdf_path), "extracted_data": json.loads(content)}
    except Exception as e:
        return {"error": str(e)}

def ingest_policies_for_payer(payer_dir, payer_name, vectorstore, llm, prompt_template):
    if not os.path.exists(payer_dir): return
    pdf_files = [f for f in os.listdir(payer_dir) if f.lower().endswith('.pdf')]
    for pdf_file in pdf_files:
        pdf_path = os.path.join(payer_dir, pdf_file)
        if rules_cache.load() and any(r.get("file") == pdf_file for r in rules_cache.load()):
             print(f"Skipping {pdf_file} (cached)")
             continue
        
        result = extract_policy_details_sync(pdf_path, llm, prompt_template)
        if "error" in result: continue
        
        data = result["extracted_data"]
        # Format for Chroma
        texts = [
            f"=== REQUIRED DOCUMENTS ===\n" + "\n".join([str(d) for d in data.get("required_documents", [])]),
            f"=== ELIGIBILITY RULES ===\n" + "\n".join([str(d) for d in data.get("eligibility_criteria", [])]),
            f"=== FORMAT ===\n" + json.dumps(data.get("pa_document_format", {}))
        ]
        metadatas = [{"doc_type": t, "payer": payer_name, "source_file": pdf_file} for t in ["required_documents", "eligibility_criteria", "pa_document_format"]]
        vectorstore.add_texts(texts=texts, metadatas=metadatas)
        rules_cache.update_rule(pdf_file, result)
        print(f"Ingested {pdf_file}")

def run_ingestion():
    setup_phoenix()
    vectorstore = get_policy_vectorstore() or Chroma(
        persist_directory=os.path.join(backend_dir, ".chroma_db"),
        embedding_function=get_embeddings(),
        collection_name="policies_collection"
    )
    llm = RobustLLM.get_llm_for_task(task="policy_extraction")
    prompt = get_policy_extraction_prompt()
    base_dir = os.path.join(backend_dir, "policy-pdfs")
    
    ingest_policies_for_payer(base_dir, "General", vectorstore, llm, prompt)
    for d_name, p_name in PAYER_DIRECTORY_MAP.items():
        ingest_policies_for_payer(os.path.join(base_dir, d_name), p_name, vectorstore, llm, prompt)
    print("Policy ingestion complete.")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARIZATION & EXTRACTION logic
# ─────────────────────────────────────────────────────────────────────────────

async def run_summarization(case_id: str):
    setup_phoenix()
    target_dir = os.path.join(backend_dir, "uploads", case_id)
    if not os.path.exists(target_dir):
        print(f"Not found: {target_dir}"); return
        
    llm = RobustLLM.get_llm_for_task(task="summarization")
    prompt = get_pdf_summarization_prompt()
    files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.lower().endswith(".pdf")]
    
    async def task(p):
        text = "\n".join([pg.extract_text() for pg in PdfReader(p).pages if pg.extract_text()])
        res = await llm.ainvoke(prompt.invoke({"document_text": text}))
        return {"file": os.path.basename(p), "summary": res.content}

    results = await asyncio.gather(*[task(f) for f in files])
    output = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
    with open(output, 'w') as f: json.dump(results, f, indent=4)
    print(f"Summarized {len(results)} files to {output}")

# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AutoAuth Centralized Business Scripts")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("migrate", help="Run DB migrations")
    subparsers.add_parser("seed", help="Seed database with mock data")
    subparsers.add_parser("recreate-db", help="Recreate EHR/Case tables (CAUTION: DESTRUCTIVE)")
    subparsers.add_parser("ingest", help="Ingest all policies into ChromaDB")
    
    sum_parser = subparsers.add_parser("summarize", help="Summarize patient PDFs for a case")
    sum_parser.add_argument("case_id", help="Case identifier")

    args = parser.parse_args()

    if args.command == "migrate":
        migrate_db()
    elif args.command == "seed":
        seed_db()
    elif args.command == "recreate-db":
        recreate_ehr_table()
    elif args.command == "ingest":
        run_ingestion()
    elif args.command == "summarize":
        asyncio.run(run_summarization(args.case_id))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
