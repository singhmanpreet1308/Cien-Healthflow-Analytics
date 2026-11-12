import duckdb
import pandas as pd

from cienmed import config

# table, so this is a reference mapping, not what a patient actually takes.
DX_TO_MED_CLASS = {
    "I10": ["Antihypertensive"],
    "I25.10": ["Statin", "Anticoagulant", "Antihypertensive"],
    "I48.91": ["Anticoagulant"],
    "E11.9": ["Antidiabetic"],
    "E78.5": ["Statin"],
    "E55.9": ["Vitamin"],
    "D50.9": ["Vitamin"],
    "F32.9": ["Antidepressant"],
    "G47.0": ["Antidepressant"],
    "J45.9": ["Bronchodilator"],
    "J44.1": ["Bronchodilator", "Antibiotic"],
    "J18.9": ["Antibiotic"],
    "J02.9": ["Antibiotic", "Analgesic"],
    "N39.0": ["Antibiotic"],
    "K21.0": ["Antacid"],
    "K29.7": ["Antacid"],
    "M17.9": ["Analgesic"],
    "M54.5": ["Analgesic"],
    "M79.3": ["Analgesic"],
    "G43.9": ["Analgesic"],
    "R51": ["Analgesic"],
    "R10.9": ["Antacid", "Analgesic"],
}


def _clean_frames() -> dict[str, pd.DataFrame]:
    raw = config.DATA_RAW

    patients = pd.read_csv(raw / "patients.csv", dtype={"phone": str})
    patients["date_of_birth"] = pd.to_datetime(patients["date_of_birth"], format="%d/%m/%Y")
    patients["registration_date"] = pd.to_datetime(patients["registration_date"], format="%d/%m/%Y")
    patients["phone"] = patients["phone"].str.lstrip("-")
    patients["insurance_provider"] = patients["insurance_provider"].fillna("Uninsured")
    patients["insurance_plan_type"] = patients["insurance_plan_type"].fillna("None")

    claims = pd.read_csv(raw / "claims.csv")
    claims["claim_date"] = pd.to_datetime(claims["claim_date"], format="%d/%m/%Y")
    claims["payment_date"] = pd.to_datetime(claims["payment_date"], format="%d/%m/%Y", errors="coerce")

    dx = pd.read_csv(raw / "diagnoses_history.csv", parse_dates=["diagnosis_date", "follow_up_date"])
    providers = pd.read_csv(raw / "providers.csv")
    meds = pd.read_csv(raw / "medications_reference.csv")

    facility = pd.read_csv(raw / "facility_monthly_metrics.csv")
    facility["report_month"] = pd.to_datetime(facility["report_month"] + "-01")

    dx_map = pd.DataFrame(
        [(code, cls) for code, classes in DX_TO_MED_CLASS.items() for cls in classes],
        columns=["diagnosis_code", "medication_category"],
    )

    return {
        "patients": patients,
        "providers": providers,
        "claims": claims,
        "diagnoses": dx,
        "medications": meds,
        "facility_metrics": facility,
        "dx_medication_class": dx_map,
    }

VIEWS_SQL = """
CREATE OR REPLACE VIEW v_claims_enriched AS
SELECT c.*,
       date_trunc('month', c.claim_date)            AS claim_month,
       c.billed_amount - c.approved_amount          AS revenue_leakage,
       (c.claim_status = 'Denied')::INT             AS is_denied,
       p.insurance_provider, p.insurance_plan_type,
       pr.specialization, pr.facility_name, pr.facility_city, pr.facility_state, pr.facility_type
FROM claims c
LEFT JOIN patients  p  USING (patient_id)
LEFT JOIN providers pr USING (provider_id);

CREATE OR REPLACE VIEW v_insurer_denials AS
SELECT insurance_provider,
       count(*)                                    AS total_claims,
       sum(is_denied)                              AS denied_claims,
       round(100.0 * sum(is_denied) / count(*), 2) AS denial_rate_pct,
       sum(billed_amount)                          AS billed,
       sum(approved_amount)                        AS approved
FROM v_claims_enriched
GROUP BY 1;

CREATE OR REPLACE VIEW v_patient_diagnoses AS
SELECT d.*, pr.provider_name, pr.specialization, pr.facility_name
FROM diagnoses d LEFT JOIN providers pr USING (provider_id);

-- Readmission proxy: a new diagnosis for the same patient within 30 days
CREATE OR REPLACE VIEW v_readmission_proxy AS
SELECT *,
       (next_dx_date IS NOT NULL
        AND datediff('day', diagnosis_date, next_dx_date) <= 30)::INT AS readmit_30d
FROM (
    SELECT d.*,
           lead(diagnosis_date) OVER (PARTITION BY patient_id
                                      ORDER BY diagnosis_date, record_id) AS next_dx_date
    FROM diagnoses d
);
"""

def build(db_path=config.DB_PATH) -> duckdb.DuckDBPyConnection:
    frames = _clean_frames()
    con = duckdb.connect(str(db_path))
    for name, df in frames.items():
        con.register("_tmp", df)                                     # expose DataFrame to SQL
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    con.execute(VIEWS_SQL)
    return con


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Every other module calls this. Builds the DB on first use."""
    if not config.DB_PATH.exists():
        build().close()
    return duckdb.connect(str(config.DB_PATH), read_only=read_only)


if __name__ == "__main__":
    con = build()
    for (t,) in con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY 1"
    ).fetchall():
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t:25s} {n:>8,}")
    con.close()