"""Admin/BA Report Agent — deterministic KPI queries + LLM narrative + charts.

The numbers come from fixed, reviewed SQL (no LLM-generated SQL), so reports
are reproducible; the LLM only writes the commentary on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import plotly.express as px

from cienmed import budget, warehouse
from cienmed.llm import get_llm

REPORT_TYPES = {
    "Executive overview": "Claims volume, approvals, denials and revenue leakage over time",
    "Claims & denials": "Denial rate by insurer, service type and denial reason",
    "Facility performance": "Revenue, wait time, satisfaction and occupancy by facility",
    "Readmission (proxy)": "30-day re-presentation by diagnosis and severity",
}


@dataclass
class Report:
    title: str
    period: str
    kpis: dict
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    figures: list = field(default_factory=list)
    narrative: str = ""

    def to_markdown(self) -> str:
        md = [f"# {self.title}", f"_Period: {self.period} · generated {date.today():%d %b %Y} by CienMed AI_", "",
              "## Key figures", *[f"- **{k}:** {v}" for k, v in self.kpis.items()], "",
              "## Commentary", self.narrative, ""]
        for name, df in self.tables.items():
            md += [f"## {name}", df.to_markdown(index=False), ""]
        return "\n".join(md)


px.defaults.color_discrete_sequence = ["#2F8CFF", "#38BDF8", "#34D399", "#1E5BB8", "#F5B83D", "#A78BFA", "#F87171"]


def inr(v: float) -> str:
    """Indian-style compact currency: crore / lakh."""
    v = float(v)
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:,.2f} Cr"
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:,.2f} L"
    return f"₹{v:,.0f}"


MONEY_COLS = {"billed", "approved", "revenue", "leakage", "billed_at_risk"}


def _for_llm(df: pd.DataFrame, max_rows: int = 40) -> pd.DataFrame:
    """Prepare a table for the LLM: money pre-formatted as ₹ Cr / L (LLMs misread raw rupee
    integers by 10x), and ALL rows sent, so 'highest/lowest' claims are made over the full table."""
    out = df.head(max_rows).copy()
    for c in out.columns:
        if c.lower() in MONEY_COLS:
            out[c] = out[c].map(inr)
    return out


def _q(con, sql, params):
    return con.execute(sql, params).df()


def build_report(kind: str, start: str, end: str, facility: str | None = None) -> Report:
    con = warehouse.connect()
    fac = "AND facility_name = $fac" if facility else ""
    p = {"s": start, "e": end, **({"fac": facility} if facility else {})}
    period = f"{start} to {end}" + (f" · {facility}" if facility else "")
    rep = Report(kind, period, {})

    if kind == "Facility performance":
        k = _q(con, f"""SELECT sum(total_revenue) rev, avg(avg_wait_time_minutes) wait,
                         avg(patient_satisfaction_score) sat, avg(bed_occupancy_rate) occ, sum(total_patients_seen) seen
                         FROM facility_metrics WHERE report_month BETWEEN $s AND $e {fac}""", p).iloc[0]
        rep.kpis = {"Patients seen": f"{int(k.seen or 0):,}", "Revenue": inr(k.rev or 0),
                    "Avg wait": f"{(k.wait or 0):.1f} min", "Satisfaction": f"{(k.sat or 0):.2f} / 5",
                    "Bed occupancy": f"{(k.occ or 0):.1f}%"}
    elif kind == "Readmission (proxy)":
        k = _q(con, f"""SELECT count(*) eps, count(DISTINCT r.patient_id) pts, avg(r.readmit_30d) rate
                         FROM v_readmission_proxy r JOIN providers USING (provider_id)
                         WHERE r.diagnosis_date BETWEEN $s AND $e {fac}""", p).iloc[0]
        rep.kpis = {"Diagnosis episodes": f"{int(k.eps):,}", "Patients": f"{int(k.pts):,}",
                    "30-day re-presentation": f"{100 * (k.rate or 0):.1f}% (proxy)"}
    else:
        k = _q(con, f"""SELECT count(*) n, sum(is_denied) denied, sum(billed_amount) billed,
                         sum(approved_amount) approved, sum(revenue_leakage) leakage FROM v_claims_enriched
                         WHERE claim_date BETWEEN $s AND $e {fac}""", p).iloc[0]
        rate = 100 * k.denied / k.n if k.n else 0
        rep.kpis = {"Claims": f"{int(k.n):,}", "Denial rate": f"{rate:.1f}%", "Billed": inr(k.billed or 0),
                    "Approved": inr(k.approved or 0), "Revenue leakage": inr(k.leakage or 0)}

    if kind == "Executive overview":
        t = _q(con, f"""SELECT claim_month AS month, count(*) claims, round(100.0*avg(is_denied),2) denial_rate_pct,
                        sum(billed_amount) billed, sum(approved_amount) approved
                        FROM v_claims_enriched WHERE claim_date BETWEEN $s AND $e {fac} GROUP BY 1 ORDER BY 1""", p)
        rep.tables["Monthly trend"] = t
        rep.figures += [px.line(t, x="month", y=["billed", "approved"], title="Billed vs approved (₹)",
                                color_discrete_map={"billed": "#2F8CFF", "approved": "#34D399"}),
                        px.bar(t, x="month", y="denial_rate_pct", title="Denial rate % by month")]
    elif kind == "Claims & denials":
        ins = _q(con, f"""SELECT insurance_provider, count(*) claims, round(100.0*avg(is_denied),2) denial_rate_pct
                          FROM v_claims_enriched WHERE claim_date BETWEEN $s AND $e {fac} GROUP BY 1 ORDER BY 3 DESC""", p)
        rsn = _q(con, f"""SELECT denial_reason, count(*) denied_claims, sum(billed_amount) billed_at_risk
                          FROM v_claims_enriched WHERE is_denied=1 AND claim_date BETWEEN $s AND $e {fac}
                          GROUP BY 1 ORDER BY 2 DESC""", p)
        svc = _q(con, f"""SELECT service_type, count(*) claims, round(100.0*avg(is_denied),2) denial_rate_pct,
                          sum(revenue_leakage) leakage FROM v_claims_enriched
                          WHERE claim_date BETWEEN $s AND $e {fac} GROUP BY 1 ORDER BY 4 DESC""", p)
        rep.tables.update({"Denial rate by insurer": ins, "Denial reasons": rsn, "By service type": svc})
        rep.figures += [px.bar(ins, x="insurance_provider", y="denial_rate_pct", title="Denial rate % by insurer"),
                        px.bar(rsn, x="denial_reason", y="denied_claims", title="Denied claims by reason")]
    elif kind == "Facility performance":
        f = _q(con, f"""SELECT facility_name, sum(total_revenue) revenue, round(avg(avg_wait_time_minutes),1) avg_wait_min,
                        round(avg(patient_satisfaction_score),2) satisfaction, round(avg(bed_occupancy_rate),1) occupancy_pct,
                        sum(emergency_visits) emergency_visits FROM facility_metrics
                        WHERE report_month BETWEEN $s AND $e {fac} GROUP BY 1 ORDER BY 2 DESC""", p)
        rep.tables["Facility league table"] = f
        rep.figures += [px.bar(f.head(15), x="facility_name", y="revenue", title="Revenue by facility (top 15)"),
                        px.scatter(f, x="avg_wait_min", y="satisfaction", size="revenue", hover_name="facility_name",
                                   title="Wait time vs satisfaction")]
    else:  # Readmission
        r = _q(con, f"""SELECT r.diagnosis_description, r.severity, count(*) episodes,
                        round(100.0*avg(r.readmit_30d),2) readmit_30d_pct
                        FROM v_readmission_proxy r JOIN providers USING (provider_id)
                        WHERE r.diagnosis_date BETWEEN $s AND $e {fac} GROUP BY 1,2 HAVING count(*) >= 20
                        ORDER BY 4 DESC LIMIT 25""", p)
        rep.tables["Highest 30-day re-presentation (proxy)"] = r
        rep.figures.append(px.bar(r.head(15), x="diagnosis_description", y="readmit_30d_pct", color="severity",
                                  title="Readmission proxy % (top 15)"))
    con.close()

    ctx = "\n".join(f"{k}: {v}" for k, v in rep.kpis.items()) + "\n\n" + "\n\n".join(
        f"{n} (all {len(d)} rows):\n{_for_llm(d).to_string(index=False)}" for n, d in rep.tables.items())
    try:
        rep.narrative = get_llm().chat(
            "You are a healthcare business analyst. Write a 120-180 word commentary for hospital leadership: "
            "3 key findings with numbers, then 2 recommendations. Use ONLY the CONTEXT; every number you quote must "
            "appear in it. Do not call a difference 'significant' unless the context shows it is large. "
            "Only say 'highest' or 'lowest' after checking every row of the relevant table. Treat rates from fewer "
            "than 50 episodes or claims as unreliable. Readmission figures are a proxy. Money is already formatted in ₹.",
            f"Report: {kind}, period {period}\n\nCONTEXT:\n{ctx}")
    except budget.BudgetExceeded as e:
        rep.narrative = f"⏳ AI commentary unavailable: {e}"
    return rep