"""Pre-answer every example question and demo report with Euri, and save ONLY those answers to
data/demo_cache.json (committed to GitHub). Guest accounts can then use them at zero token cost,
even on Streamlit Cloud where the normal cache is wiped on every restart.

Run once (with Euri), after any change to prompts, data or examples:
    python build_demo_cache.py
Cost: one route + one answer per example (~2-4 calls each), only for answers not already cached.
"""
import json

from cienmed import budget, config, orchestrator, reports
from cienmed.examples import DEMO_REPORTS, EXAMPLES
from cienmed.llm import CachedLLM, get_llm

llm = get_llm()
if not isinstance(llm, CachedLLM):
    raise SystemExit("Run this with Euri and the cache enabled (unset CIENMED_LLM=mock).")

budget.set_user("_system")
users = {"clinician": {"username": "_system", "role": "clinician"},
         "admin": {"username": "_system", "role": "admin"}}
for role, questions in EXAMPLES.items():
    for q in questions:
        r = orchestrator.answer(q, users[role])
        print(f"[{role}] {q} -> {r.tool}")
for kind, start, end, facility in DEMO_REPORTS:
    reports.build_report(kind, start, end, facility)
    print(f"[report] {kind}")

demo = {k: llm.lookup(k) for k in sorted(llm.used_keys) if llm.lookup(k) is not None}
config.DEMO_CACHE_PATH.write_text(json.dumps(demo, indent=1), encoding="utf-8")
print(f"\nSaved {len(demo)} pre-answered prompts to {config.DEMO_CACHE_PATH}")
print(llm.stats())