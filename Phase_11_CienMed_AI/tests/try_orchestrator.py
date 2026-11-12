"""Manual check for Step 9.

Run FREE first (offline mock):   set CIENMED_LLM=mock   then   python -m tests.try_orchestrator
Then ONCE with Euri:             set CIENMED_LLM=       then   python -m tests.try_orchestrator
Re-runs with Euri come from the cache.
"""
from cienmed import config, orchestrator
from cienmed.llm import get_llm

DOC = {"username": "dr.demo", "role": "clinician"}
ADM = {"username": "admin.demo", "role": "admin"}

CASES = [
    (DOC, "Summarise patient 3's medical history", "patient_summary"),
    (DOC, "What medications is patient 3 taking?", "medications"),       # has a PDF report -> real meds
    (DOC, "What medications is patient 12224 taking?", "medications"),   # no report -> typical classes
    (DOC, "Does patient 1904 have any allergies?", "allergies"),
    (DOC, "Does patient 12224 have any allergies?", "allergies"),        # no report -> UNKNOWN
    (DOC, "Which patients are allergic to peanuts?", "allergy_search"),
    (DOC, "What is patient 12224's readmission risk?", "ml"),
    (DOC, "Summarise Aryan's history", "patient_summary"),               # several Aryans -> must ask
    (DOC, "How many patients have both CKD stage 3 and pneumonia?", "sql"),
    (ADM, "Which insurers have the highest claim denial rate?", "sql"),
    (ADM, "Which open claims are most likely to be denied?", "ml"),
    (ADM, "How is the readmission rate defined?", "rag"),
    (ADM, "Summarise patient 3's medical history", None),                 # admin has no patient tools
]

print(f"LLM backend: {config.LLM_BACKEND}\n")
for user, q, expected in CASES:
    r = orchestrator.answer(q, user)
    ok = "OK " if (expected is None and r.tool in orchestrator.ROLE_TOOLS["admin"]) or r.tool == expected else "?? "
    print(f"{ok}[{user['role']}] {q}\n    tool={r.tool}  rows={None if r.data is None else len(r.data)}"
          f"  choices={None if r.needs_choice is None else len(r.needs_choice)}")
    print("    " + r.answer.replace("\n", "\n    ")[:400] + "\n")

if hasattr(get_llm(), "stats"):
    print(get_llm().stats())