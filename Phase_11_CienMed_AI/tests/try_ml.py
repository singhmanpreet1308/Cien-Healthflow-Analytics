"""Manual check for Step 7 — (scikit-learn runs locally)."""
import json

import pandas as pd

from cienmed.tools import ml_tool

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 10)

print("=== Model cards")
for card in ml_tool.model_cards():
    print(json.dumps({k: card[k] for k in ("model", "train_rows", "test_rows", "base_rate", "roc_auc", "pr_auc")}))
    print("   ", card["interpretation"])

print("\n=== Readmission risk, patient 12224")
r = ml_tool.patient_readmission_risk(12224)
print({k: r[k] for k in ("score", "band", "based_on")})

print("\n=== Readmission risk, patient 5 (no diagnoses -> expect None)")
print(ml_tool.patient_readmission_risk(5))

print("\n=== Top 10 open claims by denial risk")
queue, card = ml_tool.claim_denial_scores(limit=10)
print(queue.to_string(index=False))
print("\nBand counts across ALL open claims:")
print(ml_tool.claim_denial_scores(limit=100000)[0].band.value_counts())