"""CienMed AI orchestrator.

question ─► route (LLM picks ONE tool for this role) ─► run tool (grounded facts)
         ─► mask PHI for the role ─► LLM writes the answer from the facts only ─► audit log
"""
import json
from dataclasses import dataclass, field

import pandas as pd

import re

from cienmed import budget, governance
from cienmed.llm import get_llm, parse_json
from cienmed.tools import ml_tool, patient_tool, rag_tool, report_tool, sql_tool

# The tool menu each role sees. The descriptions ARE the routing logic — the LLM reads them.
ROLE_TOOLS = {
    "clinician": {
        "patient_summary": "Summarise ONE named/numbered patient's history. args: patient_id (int) or patient_name (str)",
        "medications": "ONE patient's medications. args: patient_id or patient_name",
        "allergies": "ONE patient's allergies. args: patient_id or patient_name",
        "cardiac_history": "Whether ONE patient has had cardiac diagnoses. args: patient_id or patient_name",
        "ml": "ONE patient's 30-day readmission risk. args: patient_id or patient_name",
        "allergy_search": "Which patients are allergic to something (across all reports). args: allergen (str, optional)",
        "sql": "Counts, lists, filters or trends across MANY patients (e.g. 'how many patients have X and Y'). args: question",
        "rag": "Definitions, policies, data dictionary, or fuzzy search of clinical notes. args: query",
    },
    "admin": {
        "sql": "Operational / financial / claims / facility analytics: counts, rates, rankings, trends. args: question",
        "ml": "Work queue of open claims ranked by predicted denial risk. args: limit (int, optional)",
        "rag": "Definitions, KPI meanings, governance and data policies. args: query",
    },
}
PATIENT_TOOLS = {"patient_summary", "medications", "allergies", "cardiac_history"}

ROUTER_SYSTEM = """[ROUTER] You route questions for CienMed AI, a hospital assistant.
The user's role is {role}. Choose exactly ONE tool from this menu:
{menu}
Reply with JSON only: {{"tool": "<name>", "args": {{...}}}}
Rules: a question about ONE specific patient uses a patient tool, never sql or rag.
Exact counts or filters across patients use sql, never rag.
Pass patient_id when a number is given, otherwise patient_name. If nothing fits, use "rag"."""

ANSWER_SYSTEM = """You are CienMed AI, a hospital decision-support assistant answering a {role}.
Answer ONLY from the CONTEXT. If the context does not contain the answer, say so plainly.
Lead with the direct answer, then 2-5 short bullet points of supporting detail.
{role_style}
Never invent patients, numbers, medications or allergies. This is decision support, not a diagnosis."""

ROLE_STYLE = {
    "clinician": "Use clinical language. Highlight chronic conditions, severity, active medications, allergies and follow-ups.",
    "admin": "Use business language. Quantify (counts, %, currency) and end with one actionable recommendation.",
}


@dataclass
class Response:
    answer: str
    tool: str
    data: pd.DataFrame | None = None
    sql: str | None = None
    sources: list[str] = field(default_factory=list)
    model_card: dict | None = None
    needs_choice: pd.DataFrame | None = None   # several patients matched a name


# ---------------------------------------------------------------- routing
def route(question: str, role: str) -> dict:
    menu = "\n".join(f"- {k}: {v}" for k, v in ROLE_TOOLS[role].items())
    try:
        decision = parse_json(get_llm().chat(ROUTER_SYSTEM.format(role=role, menu=menu), question))
    except budget.BudgetExceeded:
        raise
    except Exception:
        decision = {}
    # Never trust the router blindly: a tool outside this role's menu falls back to rag
    if decision.get("tool") not in ROLE_TOOLS[role]:
        decision = {"tool": "rag", "args": {"query": question}}
    decision.setdefault("args", {})
    return decision


def _resolve_patient(args: dict) -> tuple[int | None, pd.DataFrame | None]:
    """patient_id wins; a name with several matches returns the choices instead of guessing."""
    if args.get("patient_id"):
        return int(args["patient_id"]), None
    name = args.get("patient_name")
    if not name:
        return None, None
    matches = patient_tool.find_patients(name)
    if len(matches) == 1:
        return int(matches.patient_id.iloc[0]), None
    return None, matches


def _ground(question: str, role: str, context: str) -> str:
    system = ANSWER_SYSTEM.format(role=role, role_style=ROLE_STYLE[role])
    return get_llm().chat(system, f"QUESTION: {question}\n\nCONTEXT:\n{context}")


def _table(df: pd.DataFrame | None, empty: str) -> str:
    return df.to_string(index=False) if df is not None and not df.empty else empty


# ---------------------------------------------------------------- main entry
def answer(question: str, user: dict, forced_patient_id: int | None = None) -> Response:
    role = user["role"]
    budget.set_user(user["username"])
    tool, args = "none", {}
    try:
        decision = route(question, role)
        tool, args = decision["tool"], decision["args"]
        if forced_patient_id:
            args["patient_id"] = forced_patient_id
        resp = _dispatch(question, role, tool, args)
    except budget.BudgetExceeded as e:   # token limit reached: friendly message, no API call made
        resp = Response(f"⏳ {e}", "budget")
    except Exception as e:   # never crash the UI; report and log instead
        resp = Response(f"Sorry — that request failed ({type(e).__name__}: {e}).", tool)

    if resp.data is not None:
        resp.data = governance.mask_df(resp.data, role)
    resp.answer = governance.mask_text(resp.answer, role)
    governance.audit(user, question, tool, args=json.dumps(args, default=str), sql=resp.sql,
                     rows=None if resp.data is None else len(resp.data))
    return resp


def _dispatch(question: str, role: str, tool: str, args: dict) -> Response:
    # ---- tools about ONE patient (clinician only)
    if tool in PATIENT_TOOLS or (tool == "ml" and role == "clinician"):
        pid, choices = _resolve_patient(args)
        if choices is not None and not choices.empty:
            return Response(f"I found {len(choices)} patients matching that name. Which one do you mean?",
                            tool, needs_choice=choices)
        if pid is None:
            return Response("Which patient? Give a patient ID or full name.", tool)
        rec = patient_tool.get_patient(pid)
        if rec is None:
            return Response(f"No patient with ID {pid} exists in the warehouse.", tool)
        has_report = pid in report_tool.report_files()
        return _patient_tool(question, role, tool, pid, rec, has_report)

    # ---- across patients / operations
    if tool == "allergy_search":
        df = report_tool.all_allergies()
        allergen = (args.get("allergen") or "").strip()
        if allergen:
            df = df[df.allergen.str.contains(allergen, case=False, na=False)]
        n_reports = len(report_tool.report_files())
        ctx = (f"Allergies found in {n_reports} medical-history reports (patients without a report are NOT "
               f"covered):\n{_table(df, 'no matching allergies recorded')}")
        return Response(_ground(question, role, ctx), tool, data=df, sources=["medical_reports"])

    if tool == "ml":   # admin work queue
        df, mc = ml_tool.claim_denial_scores(int(args.get("limit") or 20))
        ctx = (f"Top open claims by predicted denial risk:\n{df.head(10).to_string(index=False)}\n\n"
               f"Model ROC-AUC {mc['roc_auc']}, base rate {mc['base_rate']}. {mc['interpretation']}")
        return Response(_ground(question, role, ctx), tool, data=df, model_card=mc, sources=["claim_denial model"])

    if tool == "sql":
        res = sql_tool.ask(args.get("question") or question, role)
        if res.error:
            return Response(res.error, tool, sql=res.sql or None)
        preview = governance.mask_df(res.df, role).head(30).to_string(index=False)
        ctx = f"SQL: {res.sql}\nRows returned: {len(res.df)}\nResult:\n{preview}"
        return Response(_ground(question, role, ctx), tool, data=res.df, sql=res.sql, sources=res.tables)

    if role == "admin" and re.search(r"\bpatient\s*#?\d+", question, re.I):
        return Response("Individual patient records aren't available to the admin role. "
                        "Ask about claims, facilities or aggregate trends instead.", "rag")
    hits = rag_tool.retrieve(args.get("query") or question, role, k=5)
    if not hits:
        return Response("I couldn't find anything relevant in the knowledge base.", "rag")
    ctx = "\n\n".join(f"[{c.source} | {c.id}]\n{c.text[:1200]}" for c, _ in hits)
    return Response(_ground(question, role, ctx), "rag", sources=sorted({c.id for c, _ in hits}))


def _patient_tool(question, role, tool, pid, rec, has_report) -> Response:
    report_note = "" if has_report else "\n(No medical-history report on file for this patient.)"

    if tool == "patient_summary":
        ctx = rec.facts_text() + report_note
        if has_report:
            s = report_tool.sections(pid)
            ctx += (f"\n\nFrom medical-history report:\nMedications:\n{_table(report_tool.medications(pid), 'none recorded')}"
                    f"\nAllergies: {s.get('Allergies', 'not stated')}"
                    f"\nSurgeries and procedures: {s.get('Surgeries and Procedures', 'not stated')}")
        data = rec.diagnoses[["diagnosis_date", "diagnosis_code", "diagnosis_description", "severity",
                              "is_chronic", "treatment_plan", "specialization", "follow_up_date"]]
        return Response(_ground(question, role, ctx), tool, data=data,
                        sources=["patients", "diagnoses", "claims"] + ([f"medical_history_{pid}.pdf"] if has_report else []))

    if tool == "medications":
        if has_report:   # actual medications from the report
            meds = report_tool.medications(pid)
            ctx = (f"{rec.facts_text(5)}\n\nMedications from the patient's medical-history report "
                   f"(actual record):\n{_table(meds, 'None recorded.')}")
            return Response(_ground(question, role, ctx), tool, data=meds, sources=[f"medical_history_{pid}.pdf"])
        meds = patient_tool.medication_classes(pid)   # fallback: typical classes only
        ctx = (f"{rec.facts_text(5)}\n\nIMPORTANT: no medical-history report and no prescription records exist "
               f"for this patient. Typical medication CLASSES for the recorded diagnoses (reference mapping, "
               f"NOT the patient's actual medications):\n{_table(meds, 'none mapped')}")
        return Response(_ground(question, role, ctx), tool, data=meds, sources=["dx_medication_class"])

    if tool == "allergies":
        if not has_report:
            return Response(f"Allergy status for patient {pid} is UNKNOWN: there is no medical-history report "
                            f"on file. Check allergies directly before prescribing.", tool)
        al = report_tool.allergies(pid)
        ctx = f"{rec.facts_text(3)}\n\nAllergies from report:\n{_table(al, 'None known (report states no known allergies).')}"
        return Response(_ground(question, role, ctx), tool, data=al, sources=[f"medical_history_{pid}.pdf"])

    if tool == "cardiac_history":
        cardiac = patient_tool.cardiac_history(rec)
        ctx = (f"{rec.facts_text(3)}\n\nCardiac diagnoses (I10, I25.10, I48.91): {len(cardiac)}\n"
               f"{_table(cardiac[['diagnosis_date', 'diagnosis_description', 'severity', 'treatment_plan']], 'none')}")
        return Response(_ground(question, role, ctx), tool, data=cardiac, sources=["diagnoses"])

    # ml (clinician): readmission risk
    risk = ml_tool.patient_readmission_risk(pid)
    if risk is None:
        return Response(f"Patient {pid} has no diagnosis episodes, so no readmission risk can be computed.", tool)
    mc = risk["model_card"]
    ctx = (f"{rec.facts_text(5)}\n\n30-day readmission (proxy) risk: {risk['score']} ({risk['band']}), based on "
           f"latest episode {risk['based_on']}. Model ROC-AUC {mc['roc_auc']} vs base rate {mc['base_rate']}. "
           f"{mc['interpretation']}")
    return Response(_ground(question, role, ctx), tool, model_card=mc, sources=["readmission_30d model"])