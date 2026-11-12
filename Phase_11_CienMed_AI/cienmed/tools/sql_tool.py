"""Text-to-SQL agent over the local DuckDB warehouse, with guardrails.

Flow: scope check (code) -> LLM writes SQL -> guardrails validate -> DuckDB runs it
      -> on a DuckDB error, the error goes back to the LLM for one self-repair retry.
"""
import re
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from cienmed import config, warehouse
from cienmed.llm import get_llm

# Plain-English notes help the LLM pick the right table
TABLE_NOTES = {
    "claims": "one row per insurance claim; claim_status in (Approved, Denied, Pending, Under Review)",
    "v_claims_enriched": "claims joined to patient insurer and provider/facility; has claim_month, is_denied, revenue_leakage",
    "v_insurer_denials": "pre-aggregated denial rate by insurance_provider",
    "patients": "patient master (PHI). insurance_provider='Uninsured' when missing",
    "providers": "doctors with specialization and facility",
    "diagnoses": "diagnosis episodes per patient (ICD-10 codes), severity, is_chronic, treatment_plan",
    "v_patient_diagnoses": "diagnoses joined to provider name/specialization/facility",
    "v_readmission_proxy": "diagnoses with readmit_30d flag = new episode within 30 days (proxy)",
    "facility_metrics": "monthly KPIs per facility (report_month is a DATE, first of month); "
                        "avg_wait_time_minutes is the patient wait time",
    "medications": "medication reference catalogue (not patient prescriptions)",
    "dx_medication_class": "reference mapping diagnosis_code -> typical medication_category",
}

# Role-based access: which tables each role may query
ROLE_TABLES = {
    "admin": set(TABLE_NOTES),
    "clinician": {"patients", "providers", "diagnoses", "v_patient_diagnoses", "v_readmission_proxy",
                  "medications", "dx_medication_class", "claims", "v_claims_enriched"},
}

# Concepts that only exist in one table. If the role can't see that table,
# refuse up front (in code) instead of letting the LLM reinterpret the question.
CONCEPT_TABLES = {
    r"\bwait(ing)?[\s_-]*times?\b": "facility_metrics",
    r"\b(bed\s*)?occupancy\b": "facility_metrics",
    r"\bsatisfaction\b": "facility_metrics",
    r"\bstaff(ing)?\b": "facility_metrics",
    r"\bemergency\s+visits?\b": "facility_metrics",
}


def concept_block(question: str, role: str) -> str | None:
    """Return a refusal reason if the question needs a table this role can't access."""
    for pattern, table in CONCEPT_TABLES.items():
        match = re.search(pattern, question, re.I)
        if match and table not in ROLE_TABLES[role]:
            return (f"'{match.group(0)}' is facility operations data, "
                    f"which isn't available to the {role} role.")
    return None


def schema_prompt(role: str) -> str:
    """Build the table/column list for this role straight from the database."""
    con = warehouse.connect()
    lines = []
    for t in sorted(ROLE_TABLES[role]):
        cols = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [t]
        ).fetchall()
        lines.append(f"- {t}: {TABLE_NOTES[t]}\n    columns: " + ", ".join(f"{c} {d}" for c, d in cols))

    # Exact diagnosis codes, so the LLM filters by code instead of guessing description text
    codes = con.execute(
        "SELECT DISTINCT diagnosis_code, diagnosis_description FROM diagnoses ORDER BY 1"
    ).fetchall()
    lines.append("\nDiagnosis codes: " + "; ".join(f"{c}={d}" for c, d in codes))
    con.close()
    return "\n".join(lines)


SYSTEM = """[TEXT2SQL] You are a DuckDB SQL expert for a hospital analytics warehouse.
Write ONE read-only DuckDB SELECT (or WITH ... SELECT) query answering the question.
Rules: use only the tables below; prefer the v_* views; round percentages to 2 dp;
add ORDER BY for rankings; never select phone, email or date_of_birth unless explicitly asked.
Dates (DuckDB dialect, NOT SQLite/MySQL):
  - difference between dates: date_diff('day', start_date, end_date)  (or 'hour', 'month', ...)
  - bucketing: date_trunc('month', d); parts: extract(year FROM d)
  - formatting only: strftime(d, '%Y-%m')  -- date comes FIRST; never use '%s', julianday() or unixepoch()
If the question needs data that is not in the tables below, do NOT substitute a different metric;
reply exactly: CANNOT_ANSWER: <short reason>
Return ONLY the SQL, no explanation, no markdown fences.

Tables:
{schema}
"""

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|export|pragma|install|load|call|set)\b", re.I
)


def _clean(sql: str) -> str:
    """Strip ```sql fences and trailing semicolons the LLM may add."""
    return re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.M).strip().rstrip(";")


def referenced_tables(sql: str) -> set[str]:
    """Find every table after FROM / JOIN, ignoring CTE names defined with WITH x AS (...)."""
    names = re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", sql, re.I)
    ctes = re.findall(r"\b([a-zA-Z_]\w*)\s+as\s*\(", sql, re.I)
    return {n.lower() for n in names} - {c.lower() for c in ctes}


def validate(sql: str, role: str) -> None:
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        raise PermissionError("Only SELECT queries are allowed.")
    if ";" in sql:
        raise PermissionError("Only a single statement is allowed.")
    if FORBIDDEN.search(sql):
        raise PermissionError("Query contains a forbidden keyword.")
    bad = referenced_tables(sql) - ROLE_TABLES[role]
    if bad:
        raise PermissionError(f"Role '{role}' may not query: {', '.join(sorted(bad))}")


@dataclass
class SQLResult:
    question: str
    sql: str
    df: pd.DataFrame
    attempts: int = 1          # 0 = refused before any LLM call
    error: str | None = None
    tables: list[str] = field(default_factory=list)


def run_sql(sql: str, role: str) -> pd.DataFrame:
    validate(sql, role)
    con = warehouse.connect(read_only=True)
    try:
        # Wrapping forces a row cap even if the LLM forgot LIMIT
        return con.execute(f"SELECT * FROM ({sql}) LIMIT {config.SQL_ROW_LIMIT}").df()
    finally:
        con.close()


def ask(question: str, role: str = "admin", max_retries: int = 1) -> SQLResult:
    # 1) Deterministic scope check — runs BEFORE any LLM call
    reason = concept_block(question, role)
    if reason:
        return SQLResult(question, "", pd.DataFrame(), 0, error=reason)

    # 2) LLM writes SQL, guardrails check it, DuckDB runs it
    llm = get_llm()
    system = SYSTEM.format(schema=schema_prompt(role))
    prompt = question
    sql, last_err = "", None

    for attempt in range(1, max_retries + 2):
        sql = _clean(llm.chat(system, prompt))
        if sql.upper().startswith("CANNOT_ANSWER"):
            reason = sql.split(":", 1)[-1].strip()
            return SQLResult(question, "", pd.DataFrame(), attempt,
                             error=f"This can't be answered from the data available to your role: {reason}")
        try:
            df = run_sql(sql, role)
            return SQLResult(question, sql, df, attempt, tables=sorted(referenced_tables(sql)))
        except PermissionError as e:
            # Security block: never retry, the LLM shouldn't be coached around a guardrail
            return SQLResult(question, sql, pd.DataFrame(), attempt, error=str(e))
        except duckdb.Error as e:
            # Ordinary SQL mistake (wrong column etc.): show the LLM the error and let it fix it
            last_err = str(e).splitlines()[0]
            hint = ""
            if "strftime" in last_err.lower() or "format specifier" in last_err.lower():
                hint = ("\nHint: this is DuckDB. For date differences use date_diff('day', start, end); "
                        "strftime is strftime(date, format) and has no '%s'.")
            prompt = f"{question}\n\nYour previous SQL:\n{sql}\nfailed with: {last_err}{hint}\nFix it."

    return SQLResult(question, sql, pd.DataFrame(), max_retries + 1, error=last_err)