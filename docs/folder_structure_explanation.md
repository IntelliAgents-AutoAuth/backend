# Folder Structure Explanation

This document provides a clear overview of the backend codebase, its modular architecture, and its equivalence to familiar Spring Boot concepts.

---

### 📂 Core API & Configuration

**api/v1/endpoints**
- **What It Means**: Application API Layer
- **Spring Boot Equivalent**: `@RestController`
- **Responsibility**: Handles HTTP requests (Auth, Cases, Uploads). Manages routing and response formatting.

**api/deps.py**
- **What It Means**: Dependency Provider
- **Spring Boot Equivalent**: `@Autowired` / `@Bean`
- **Responsibility**: Provides shared dependencies like database sessions (`get_db`) and authentication guards. Ensures database connections are automatically opened and closed per request.

**core**
- **What It Means**: Global Constants & Config
- **Spring Boot Equivalent**: `@Configuration`
- **Responsibility**: System-wide settings, Environment variable processing, and Security/JWT setup.

**constants**
- **What It Means**: System Constants
- **Spring Boot Equivalent**: `Static Constants`
- **Responsibility**: Centralized Enums, Status codes, and shared system-wide values.

---

### 🗄️ Persistence & Data Validation

**models**
- **What It Means**: Persistence Layer
- **Spring Boot Equivalent**: `@Entity`
- **Responsibility**: Defines database table structures (e.g., User, Case models).

**schemas**
- **What It Means**: Data Validation Layer
- **Spring Boot Equivalent**: `DTO` (Data Transfer Objects)
- **Responsibility**: Pydantic models for strictly validating API inputs and outputs.

**crud**
- **What It Means**: Data Access Layer
- **Spring Boot Equivalent**: `@Repository`
- **Responsibility**: Low-level database interaction logic (SELECT, INSERT, UPDATE, DELETE).

**db**
- **What It Means**: Database Connectivity
- **Spring Boot Equivalent**: `DataSource`
- **Responsibility**: Connection management, SQLAlchemy engine setup, and session control.

---

### 🧠 Logic & Intelligence

**services**
- **What It Means**: Business Logic Layer
- **Spring Boot Equivalent**: `@Service`
- **Responsibility**: Core logic for deterministic processing (e.g., EHR Query, Policy Fetch).

**agents**
- **What It Means**: AI Reasoning Layer
- **Spring Boot Equivalent**: *(N/A)*
- **Responsibility**: Specialized AI modules for analysis (Extraction, Gatekeeper, Appeals).

**orchestrator**
- **What It Means**: Process Coordination
- **Spring Boot Equivalent**: *(N/A)*
- **Responsibility**: Manages the execution flow between AI agents and core services.

---

### 🛠️ Utilities & Support

**utils**
- **What It Means**: Common Utilities
- **Spring Boot Equivalent**: `@Component` Utilities
- **Responsibility**: Reusable helpers for Logging, Authentication, and String manipulation.

**mock_data**
- **What It Means**: Development Assets
- **Spring Boot Equivalent**: *(N/A)*
- **Responsibility**: Synthetic datasets (EHR, Policies) used for testing/demonstrations.

**uploads**
- **What It Means**: File Storage
- **Spring Boot Equivalent**: *(N/A)*
- **Responsibility**: Organized by **Case ID**. Each case gets its own subfolder (e.g., `uploads/PA-20260301-0041/`). Used by the Extraction Agent to locate case-specific documents.

**data**
- **What It Means**: Database Storage
- **Spring Boot Equivalent**: *(N/A)*
- **Responsibility**: Local storage for SQLite databases (Proof of Concept).

**scripts**
- **What It Means**: Maintenance Utilities
- **Spring Boot Equivalent**: `schema.sql` / `data.sql`
- **Responsibility**: One-time setup, DB seeding, and initialization scripts.

**tests**
- **What It Means**: Verification Layer
- **Spring Boot Equivalent**: `JUnit / @SpringBootTest`
- **Responsibility**: Unit and integration tests for all system components.

---

### 🐍 What is `__init__.py`?

In Python, every folder that contains code that you want to import from other folders needs an `__init__.py` file inside it. It tells Python: *"This folder is a package. You can import from it."*

#### Simple Example

**Without `__init__.py`:**
```python
from agents.gatekeeper_agent import GatekeeperAgent
# ❌ Error — Python does not recognize 'agents' as a package
```

**With `__init__.py` inside `agents/`:**
```python
from agents.gatekeeper_agent import GatekeeperAgent
# ✅ Works perfectly
```

#### Spring Boot Equivalent
In **Spring Boot**, you rarely think about this because Spring automatically scans all classes in the project. In **Python**, you must explicitly tell the interpreter which folders are packages by including an `__init__.py` file.

---

### 🌟 The 3 Main Advantages in AutoAuth

#### Advantage 1: Enables Imports Across Folders
Without it, nothing can talk to anything else. With it, every module can import from any other module cleanly:
- **orchestrator** imports from **agents**
- **agents** imports from **services**
- **services** imports from **crud**
- **crud** imports from **models**
- **endpoints** imports from **schemas**

The entire AutoAuth pipeline works because of `__init__.py`. Without it, every import breaks.

#### Advantage 2: Controls What is Exposed (Abstraction)
You can use `__init__.py` to simplify imports for other developers:
```python
# Inside agents/__init__.py
from .gatekeeper_agent import GatekeeperAgent
from .extraction_agent import ExtractionAgent
```
Now, anyone importing gets a clean, professional import:
```python
# With __init__.py content
from agents import GatekeeperAgent
```

#### Advantage 3: Prevents Naming Conflicts
Imagine you have `services/utils.py` and `agents/utils.py`. Because each folder is its own package thanks to `__init__.py`, Python knows exactly which `utils` you mean when you import. No conflict, no confusion.

---

### ✅ One Line Summary
> **`__init__.py` turns a folder into a smart importable package.**
> Without it, your project is just a collection of disconnected files.
> With it, your project is a connected professional codebase.



> [!TIP]
> This spacing and structure is designed for readability. When adding new modules, follow this hierarchical pattern to maintain a clean codebase.