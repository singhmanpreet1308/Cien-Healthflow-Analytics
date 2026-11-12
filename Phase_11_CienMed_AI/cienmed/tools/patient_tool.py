"""Structured patient retrieval for the Clinician Assistant.

Facts come straight from fixed SQL (grounded). The LLM only writes the narrative
on top of these facts, in the orchestrator (Step 9).
"""
from dataclasses import dataclass

import pandas as pd

from cienmed import warehouse

CARDIAC_CODES = ("I10", "I25.10", "I48.91")   # Hypertension, CAD, Atrial fibrillation


@dataclass
class PatientRecord:
    patient: dict              # one row from patients
    diagnoses: pd.DataFrame    # all diagnosis episodes, newest first
    claims: pd.DataFrame       # all claims, newest first

    def facts_text(self, max_dx: int = 15) -> str:
        """Turn the record into compact plain text — this is what the LLM will read."""
        p = self.patient
        age = int((pd.Timestamp.today() - pd.Timestamp(p["date_of_birth"])).days // 365.25)
        chronic = sorted(self.diagnoses.loc[self.diagnoses.is_chronic, "diagnosis_description"].unique())

        lines = [
            f"Patient {p['patient_id']}: {p['first_name']} {p['last_name']}, {age}y, gender {p['gender']}, "
            f"blood group {p['blood_group']}, {p['address_city']}, {p['country']}. "
            f"Insurance: {p['insurance_provider']} ({p['insurance_plan_type']}).",
            f"Diagnosis episodes on record: {len(self.diagnoses)}; chronic: {', '.join(chronic) or 'none'}.",
        ]
        for r in self.diagnoses.head(max_dx).itertuples():
            lines.append(
                f"- {r.diagnosis_date:%Y-%m-%d} {r.diagnosis_code} {r.diagnosis_description} "
                f"[{r.severity}{', chronic' if r.is_chronic else ''}] by {r.provider_name} ({r.specialization}); "
                f"plan: {r.treatment_plan}; follow-up {r.follow_up_date:%Y-%m-%d}"
            )
        if not self.claims.empty:
            denied = int((self.claims.claim_status == "Denied").sum())
            lines.append(f"Claims: {len(self.claims)} total, {denied} denied, "
                         f"billed {int(self.claims.billed_amount.sum()):,}.")
        return "\n".join(lines)


def find_patients(name: str, limit: int = 10) -> pd.DataFrame:
    """Search by name. 'John Doe' -> every part must match first OR last name."""
    con = warehouse.connect()
    parts = name.strip().split()
    where = " AND ".join(["(first_name ILIKE ? OR last_name ILIKE ?)"] * len(parts))
    params = [x for p in parts for x in (f"%{p}%", f"%{p}%")]
    df = con.execute(
        f"SELECT patient_id, first_name, last_name, date_of_birth, address_city "
        f"FROM patients WHERE {where} LIMIT {limit}",
        params,
    ).df()
    con.close()
    return df


def get_patient(patient_id: int) -> PatientRecord | None:
    con = warehouse.connect()
    p = con.execute("SELECT * FROM patients WHERE patient_id = ?", [patient_id]).df()
    if p.empty:
        con.close()
        return None
    dx = con.execute(
        "SELECT * FROM v_patient_diagnoses WHERE patient_id = ? ORDER BY diagnosis_date DESC", [patient_id]
    ).df()
    cl = con.execute(
        "SELECT * FROM claims WHERE patient_id = ? ORDER BY claim_date DESC", [patient_id]
    ).df()
    con.close()
    return PatientRecord(p.iloc[0].to_dict(), dx, cl)


def medication_classes(patient_id: int) -> pd.DataFrame:
    """Typical medication classes for the patient's recorded diagnoses.

    NOTE: there is no prescription table — this is a reference mapping,
    NOT what the patient is actually taking.
    """
    con = warehouse.connect()
    df = con.execute(
        """
        SELECT d.diagnosis_description, m.medication_category,
               string_agg(DISTINCT md.medication_name, ', ' ORDER BY md.medication_name) AS example_medications
        FROM diagnoses d
        JOIN dx_medication_class m USING (diagnosis_code)
        JOIN medications md ON md.category = m.medication_category
        WHERE d.patient_id = ?
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [patient_id],
    ).df()
    con.close()
    return df


def cardiac_history(rec: PatientRecord) -> pd.DataFrame:
    return rec.diagnoses[rec.diagnoses.diagnosis_code.isin(CARDIAC_CODES)]