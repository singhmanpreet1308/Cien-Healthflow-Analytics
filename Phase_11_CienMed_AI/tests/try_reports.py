"""Manual check for Step 6b — zero tokens (PDF parsing + TF-IDF run locally)."""
import pandas as pd

from cienmed.tools import rag_tool, report_tool

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 10)

files = report_tool.report_files()
print(f"Reports found: {len(files)} -> patient IDs {sorted(files)}\n")

for pid in sorted(files):
    secs = report_tool.sections(pid)
    meds = report_tool.medications(pid)
    print(f"=== Patient {pid}")
    print("  Sections:", [s for s in secs if s != "Header"])
    print("  Allergies:", secs.get("Allergies", "(missing)")[:80])
    print("  Medications:")
    print(meds.to_string(index=False) if meds is not None and not meds.empty else "    (none parsed)")
    print()

print("=== Patient with no report (expect None):", report_tool.medications(12224))

ix = rag_tool.build_index()
print(f"\nRAG index rebuilt: {len(ix['chunks']):,} chunks "
      f"({sum(c.id.startswith('report#') for c in ix['chunks'])} from PDF reports)\n")

for role, q in [("clinician", "patient 1 asthma inhaler medication"),
                ("clinician", "which patients have a known drug allergy"),
                ("admin", "which patients have a known drug allergy")]:     # admin: no report chunks
    print(f"=== [{role}] {q}")
    for chunk, score in rag_tool.retrieve(q, role, k=3):
        print(f"  {score:.3f}  {chunk.id}")
    print()