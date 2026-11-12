import os
from pathlib import Path
from dotenv import load_dotenv

PHASE_ROOT = Path(__file__).resolve().parent.parent   # Phase_11_CienMed_AI
REPO_ROOT = PHASE_ROOT.parent                          # Cien-Healthflow-Analytics

# Load .env from this phase folder, whichever folder you run from
load_dotenv(PHASE_ROOT / ".env")

# Use the shared /Data folder if the CSVs are there, else this phase's data/raw
_shared = REPO_ROOT / "Data"
_own = PHASE_ROOT / "data" / "raw"
DATA_RAW = _own if (_own / "claims.csv").exists() else REPO_ROOT / "Data"

DOCS_DIR = PHASE_ROOT / "data" / "docs"
ARTIFACTS = PHASE_ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
DB_PATH = ARTIFACTS / "healthflow.duckdb"

EURI_API_KEY = os.getenv("EURI_API_KEY", "")
EURI_BASE_URL = os.getenv("EURI_BASE_URL", "https://api.euron.one/api/v1/euri")
LLM_MODEL = os.getenv("CIENMED_LLM_MODEL", "gpt-4.1-mini")
LLM_BACKEND = os.getenv("CIENMED_LLM") or ("euri" if EURI_API_KEY else "mock")
# Cache identical LLM calls on disk so re-running tests costs nothing
LLM_CACHE = os.getenv("CIENMED_LLM_CACHE", "1") == "1"
LLM_CACHE_PATH = ARTIFACTS / "llm_cache.json"

# Max rows returned by the SQL tool for any single query
SQL_ROW_LIMIT = int(os.getenv("CIENMED_SQL_ROW_LIMIT", "200"))

RAG_INDEX_PATH = ARTIFACTS / "rag_index.joblib"

REPORTS_DIR = DOCS_DIR / "medical_reports"

MODELS_DIR = ARTIFACTS / "models"
MODELS_DIR.mkdir(exist_ok=True)

AUDIT_LOG = ARTIFACTS / "audit_log.jsonl"
USERS_FILE = PHASE_ROOT / "users.yaml"

PHI_SALT = os.getenv("PHI_SALT", "")


# --- LLM cache & token budget (Step 11b) -------------------------------------
DEMO_CACHE_PATH = PHASE_ROOT / "data" / "demo_cache.json"     # pre-answered examples (committed to GitHub)
USAGE_FILE = ARTIFACTS / "usage.json"
USER_DAILY_LIMIT = int(os.getenv("CIENMED_USER_DAILY_LIMIT", "40"))
GLOBAL_DAILY_LIMIT = int(os.getenv("CIENMED_GLOBAL_DAILY_LIMIT", "100"))
CACHE_ONLY_USERS = {u.strip().lower() for u in os.getenv(
    "CIENMED_CACHE_ONLY_USERS", "guest.clinician,guest.admin").split(",") if u.strip()}