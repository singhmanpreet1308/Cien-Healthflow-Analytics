from pathlib import Path

from cienmed import config, reports
from cienmed.llm import get_llm

out = config.ARTIFACTS / "reports"
out.mkdir(exist_ok=True)
print(f"LLM backend: {config.LLM_BACKEND}\n")

for kind in reports.REPORT_TYPES:
    rep = reports.build_report(kind, "2024-01-01", "2024-12-31")
    print(f"=== {kind}  ({rep.period})")
    for k, v in rep.kpis.items():
        print(f"   {k:16s} {v}")
    print(f"   tables : {list(rep.tables)}")
    print(f"   charts : {len(rep.figures)}")
    print("   commentary:", rep.narrative[:300].replace("\n", " "), "...\n")
    name = kind.lower().replace(" & ", "_").replace(" ", "_").replace("(", "").replace(")", "")
    (out / f"{name}.md").write_text(rep.to_markdown(), encoding="utf-8")
    for i, fig in enumerate(rep.figures):
        fig.write_html(out / f"{name}_chart{i + 1}.html", include_plotlyjs="cdn")

print("=== Facility filter: Apollo Hospital, claims & denials")
rep = reports.build_report("Claims & denials", "2024-01-01", "2024-12-31", "Apollo Hospital")
print("  ", rep.kpis)
print(f"\nSaved Markdown reports and chart HTML files to {out}")
if hasattr(get_llm(), "stats"):
    print(get_llm().stats())