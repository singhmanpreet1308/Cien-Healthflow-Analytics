"""Manual check for Step 6 — zero tokens (TF-IDF runs locally)."""
from cienmed.tools import rag_tool

ix = rag_tool.build_index()
print(f"Indexed {len(ix['chunks']):,} chunks\n")

tests = [
    ("admin", "How is the readmission rate defined?"),
    ("admin", "What happens to patient phone numbers and emails?"),
    ("clinician", "patients with chronic kidney disease and pneumonia"),
    ("admin", "patients with chronic kidney disease and pneumonia"),   # must NOT return notes
]
for role, q in tests:
    print(f"=== [{role}] {q}")
    for chunk, score in rag_tool.retrieve(q, role, k=3):
        print(f"  {score:.3f}  {chunk.id:22s} {chunk.text[:90]!r}")
    print()