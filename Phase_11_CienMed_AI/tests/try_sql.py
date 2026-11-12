"""Manual check for Step 4."""
from cienmed.tools import sql_tool
from cienmed.llm import get_llm

questions = [
    ("admin", "Which insurers have the highest claim denial rate?"),
    ("admin", "Show the monthly claim denial rate for 2024"),
    ("admin", "What are the top 5 service types by total billed amount?"),
    ("clinician", "How many patients have chronic kidney disease stage 3?"),
    ("clinician", "Which facilities have the longest average wait time?"),  # should be blocked
]

for role, q in questions:
    r = sql_tool.ask(q, role)
    print(f"\n=== [{role}] {q}")
    print("SQL:", r.sql)
    print("Attempts:", r.attempts)
    if r.error and r.attempts == 0:
        print("REFUSED (by design):", r.error)
    elif r.error:
        print("ERROR:", r.error)
    else:
         print("RESULT:\n", r.df.head(8))


print("\n=== Guardrail tests (should all say BLOCKED)")
for bad in ["DROP TABLE claims", "SELECT 1; DELETE FROM claims", "SELECT * FROM facility_metrics"]:
    try:
        sql_tool.validate(bad, "clinician")
        print("ALLOWED (problem!):", bad)
    except PermissionError as e:
        print("BLOCKED:", bad, "->", e)

print("\n" + get_llm().stats())