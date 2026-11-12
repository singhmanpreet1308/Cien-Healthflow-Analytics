"""Manual check for Step 3 — talk to Euri and parse JSON."""
from cienmed.llm import get_llm, parse_json

llm = get_llm()

reply = llm.chat(
    "Reply ONLY with JSON, no explanation.",
    'Return {"tool": "sql", "reason": "<one short reason>"} for the question: '
    "which insurer has the most denials?",
)
print("RAW REPLY:\n", reply)
print("\nPARSED DICT:\n", parse_json(reply))