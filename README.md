# AutoAuth Backend

The **AutoAuth Backend** is an AI-powered system designed to automate the Prior Authorization (PA) process in healthcare. It leverages agentic workflows, Retrieval-Augmented Generation (RAG), and modern LLM frameworks to analyze patient data against insurance policies and determine eligibility.

## 🚀 Key Features

- **Agentic Workflows**: Multi-agent system comprising Gap Analysis, Eligibility Check, and PA Document Generation agents.
- **Structured RAG**: Efficiently retrieves specific policy rules (Required Documents, Eligibility Criteria) from a ChromaDB vector store.
- **Patient Data Integration**: Processes EHR records and patient-uploaded evidence to identify clinical gaps.
- **Observability**: Fully instrumented with **Arize Phoenix** for LangChain trace analysis and debugging.
- **Admin Dashboard**: Integrated **SQLAdmin** for easy management of Users, Cases, and EHR records.
- **Automated Payer Submission**: Tools for generating and submitting structured PA packets to payers.

## 🛠 Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **ORMs/DB**: SQLAlchemy with SQlite (Configurable)
- **Vector Store**: [ChromaDB](https://www.trychroma.com/)
- **AI Framework**: [LangChain](https://www.langchain.com/)
- **LLMs Supported**: Google Gemini, OpenAI, Hugging Face
- **Observability**: [Arize Phoenix](https://phoenix.arize.com/)
- **PDF Processing**: pdfplumber, pypdf, reportlab

## 📁 Project Structure

```text
backend/
├── agents/          # AI Agent logic (Eligibility, Gap Analysis, PA Packet)
├── api/             # FastAPI routers and endpoints (v1)
├── core/            # Configuration and global settings
├── db/              # Database session and base model definitions
├── models/          # SQLAlchemy data models (User, Case, EHR)
├── scripts/         # Data migration and seeding scripts
├── services/        # Business logic and external service integrations
├── tools/           # Custom LangChain tools (PDF extraction, Policy retrieval)
├── orchestrator/    # Workflow management and case status transitions
└── main.py          # Application entry point
```

## ⚙️ Setup & Installation

### 1. Prerequisites
- Python 3.10+
- Virtual Environment (recommended)

### 2. Install Dependencies
```bash
pip install -r Requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the `backend/` directory:
```env
OPENAI_API_KEY=your_key
GOOGLE_API_KEY=your_key
PHOENIX_ENABLED=true
DATABASE_URL=sqlite:///./data/autoauth.db
```

### 4. Database Setup
The system automatically handles migrations and seeding on startup (via `main.py`). To manually seed:
```bash
python scripts/seeder.py
python scripts/ingest_policies.py
```

### 5. Running the API
```bash
uvicorn main:app --reload
```
The API will be available at `http://localhost:8000`.
- **Swagger Docs**: `http://localhost:8000/docs`
- **Admin Panel**: `http://localhost:8000/admin`
- **Phoenix Dashboard**: `http://localhost:6006`

## 📊 Observability
This project uses Arize Phoenix for tracing AI agent performance. When enabled, all LangChain runs are automatically logged, allowing you to visualize retrieval steps and LLM outputs in real-time.
