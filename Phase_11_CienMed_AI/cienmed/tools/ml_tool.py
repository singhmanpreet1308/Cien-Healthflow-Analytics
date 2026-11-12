"""Predictive insights: claim-denial risk and 30-day readmission (proxy) risk.

Both models: scikit-learn HistGradientBoosting inside a Pipeline with one-hot
encoding, time-based train/test split (no leakage from the future), metrics
saved next to the model so the app can show a model card with every score.

Train:  python -m cienmed.tools.ml_tool
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from cienmed import config, warehouse

CLAIM_CAT = ["service_type", "insurance_provider", "insurance_plan_type", "specialization", "facility_type",
             "diagnosis_code"]
CLAIM_NUM = ["billed_amount", "patient_age", "years_experience", "claim_month_num"]

READMIT_CAT = ["diagnosis_code", "severity", "treatment_plan", "specialization", "gender"]
READMIT_NUM = ["is_chronic", "patient_age", "prior_episodes", "prior_chronic", "days_since_prev"]


def _claims_frame(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT c.claim_id, c.claim_date, c.service_type, c.billed_amount, c.diagnosis_code,
               c.insurance_provider, c.insurance_plan_type, c.specialization, c.facility_type,
               pr.years_experience, month(c.claim_date) AS claim_month_num,
               date_diff('year', p.date_of_birth, c.claim_date) AS patient_age,
               c.is_denied
        FROM v_claims_enriched c
        JOIN providers pr USING (provider_id) JOIN patients p USING (patient_id)
        WHERE c.claim_status IN ('Approved', 'Denied')
        """
    ).df()


def _readmit_frame(con, patient_id: int | None = None) -> pd.DataFrame:
    where = "WHERE r.patient_id = ?" if patient_id else ""
    return con.execute(
        f"""
        SELECT r.record_id, r.patient_id, r.diagnosis_date, r.diagnosis_code, r.diagnosis_description, r.severity, r.treatment_plan,
               pr.specialization, p.gender, r.is_chronic::INT AS is_chronic,
               date_diff('year', p.date_of_birth, r.diagnosis_date) AS patient_age,
               row_number() OVER w - 1 AS prior_episodes,
               coalesce(sum(r.is_chronic::INT) OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS prior_chronic,
               coalesce(date_diff('day', lag(r.diagnosis_date) OVER w, r.diagnosis_date), 9999) AS days_since_prev,
               r.readmit_30d, r.next_dx_date
        FROM v_readmission_proxy r
        JOIN patients p USING (patient_id) JOIN providers pr USING (provider_id)
        {where}
        WINDOW w AS (PARTITION BY r.patient_id ORDER BY r.diagnosis_date, r.record_id)
        """,
        [patient_id] if patient_id else [],
    ).df()


def _pipeline(cat, num) -> Pipeline:
    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False), cat),
                             ("num", "passthrough", num)])
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=31,
                                         class_weight="balanced", random_state=42)
    return Pipeline([("pre", pre), ("clf", clf)])


def _fit(name, df, date_col, label, cat, num, cutoff) -> dict:
    train, test = df[df[date_col] < cutoff], df[df[date_col] >= cutoff]
    model = _pipeline(cat, num).fit(train[cat + num], train[label])
    p = model.predict_proba(test[cat + num])[:, 1]
    metrics = {
        "model": name,
        "train_rows": len(train), "test_rows": len(test),
        "split": f"time-based: train < {cutoff}, test >= {cutoff}",
        "base_rate": round(float(test[label].mean()), 4),
        "roc_auc": round(float(roc_auc_score(test[label], p)), 4),
        "pr_auc": round(float(average_precision_score(test[label], p)), 4),
    }
    # Calibrate the displayed score into risk bands using test-set quantiles
    metrics["band_thresholds"] = [float(np.quantile(p, 0.5)), float(np.quantile(p, 0.9))]
    metrics["interpretation"] = (
        "Near-random discrimination (AUC ~0.5): the synthetic source data has no real signal for this target. "
        "Pipeline is production-shaped; retrain on real data." if metrics["roc_auc"] < 0.6 else
        "Model shows usable discrimination; review calibration before operational use."
    )
    joblib.dump(model, config.MODELS_DIR / f"{name}.joblib")
    (config.MODELS_DIR / f"{name}_metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def train_all() -> list[dict]:
    con = warehouse.connect()
    claims, readmit = _claims_frame(con), _readmit_frame(con)
    con.close()
    readmit = readmit[readmit.next_dx_date.notna() | (readmit.diagnosis_date < "2024-12-01")]  # label observable
    return [
        _fit("claim_denial", claims, "claim_date", "is_denied", CLAIM_CAT, CLAIM_NUM, "2024-07-01"),
        _fit("readmission_30d", readmit, "diagnosis_date", "readmit_30d", READMIT_CAT, READMIT_NUM, "2024-07-01"),
    ]


def _load(name):
    path = config.MODELS_DIR / f"{name}.joblib"
    if not path.exists():
        train_all()
    return joblib.load(path), json.loads((config.MODELS_DIR / f"{name}_metrics.json").read_text())


def _band(score: float, thresholds) -> str:
    return "High" if score >= thresholds[1] else "Medium" if score >= thresholds[0] else "Low"


def patient_readmission_risk(patient_id: int) -> dict | None:
    model, m = _load("readmission_30d")
    con = warehouse.connect()
    df = _readmit_frame(con, patient_id)
    con.close()
    if df.empty:
        return None
    latest = df.sort_values("diagnosis_date").iloc[[-1]]
    score = float(model.predict_proba(latest[READMIT_CAT + READMIT_NUM])[:, 1][0])
    return {"patient_id": patient_id, "score": round(score, 3), "band": _band(score, m["band_thresholds"]),
            "based_on": f"{latest.diagnosis_description.iloc[0]} "
                        f"on {latest.diagnosis_date.iloc[0]:%Y-%m-%d}",
            "model_card": m}


def claim_denial_scores(limit: int = 20, status: str = "Pending") -> tuple[pd.DataFrame, dict]:
    """Score open claims (Pending / Under Review) — the admin's work queue."""
    model, m = _load("claim_denial")
    con = warehouse.connect()
    df = con.execute(
        """
        SELECT c.claim_id, c.claim_date, c.service_type, c.billed_amount, c.diagnosis_code,
               c.insurance_provider, c.insurance_plan_type, c.specialization, c.facility_type, c.facility_name,
               pr.years_experience, month(c.claim_date) AS claim_month_num,
               date_diff('year', p.date_of_birth, c.claim_date) AS patient_age
        FROM v_claims_enriched c JOIN providers pr USING (provider_id) JOIN patients p USING (patient_id)
        WHERE c.claim_status IN ('Pending', 'Under Review')
        """
    ).df()
    con.close()
    df["denial_risk"] = model.predict_proba(df[CLAIM_CAT + CLAIM_NUM])[:, 1].round(3)
    df["band"] = [_band(s, m["band_thresholds"]) for s in df.denial_risk]
    cols = ["claim_id", "claim_date", "facility_name", "insurance_provider", "service_type", "billed_amount",
            "denial_risk", "band"]
    return df.sort_values("denial_risk", ascending=False)[cols].head(limit), m


def model_cards() -> list[dict]:
    return [_load(n)[1] for n in ("claim_denial", "readmission_30d")]


if __name__ == "__main__":
    for m in train_all():
        print(json.dumps(m, indent=2))