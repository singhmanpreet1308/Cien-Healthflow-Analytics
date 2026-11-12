"""CienMed AI — Streamlit front end (Phase 11 of Cien HealthFlow Analytics).

Run:  streamlit run app/streamlit_app.py
Deep links for the Power BI "CienMed AI" tab buttons:
  http://localhost:8501/?role=clinician
  http://localhost:8501/?role=admin
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from cienmed import access, budget, config, governance, orchestrator, reports, theme
from cienmed.examples import EXAMPLES
from cienmed.tools import ml_tool

st.set_page_config(page_title="CienMed AI · Cien HealthFlow", page_icon="🩺", layout="wide")
theme.register_plotly_template()
st.markdown(theme.CSS, unsafe_allow_html=True)

ROLE_LABEL = {"clinician": "Clinician Assistant", "admin": "Admin / BA Report Agent"}


# ------------------------------------------------------------------ building blocks
def brand(subtitle: str) -> None:
    st.markdown(
        f'<div class="cf-brand">{theme.LOGO_SVG.format(size=52)}'
        f'<div><div class="t1">CienMed AI</div><div class="t2">Cien HealthFlow Analytics Platform</div></div></div>'
        f'<div class="cf-divider"></div><p class="cf-sub">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def auto_chart(df: pd.DataFrame):
    """Pick a sensible chart for a SQL result: line for time, bar for categories."""
    if df is None or df.empty or len(df) < 2 or len(df.columns) < 2:
        return None
    x = df.columns[0]
    nums = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not nums:
        return None
    is_time = pd.api.types.is_datetime64_any_dtype(df[x]) or any(w in x.lower() for w in ("month", "date"))
    fig = px.line(df, x=x, y=nums[0], markers=True) if is_time else px.bar(df.head(25), x=x, y=nums[0])
    fig.update_layout(height=340)
    return fig


def render_response(r: orchestrator.Response, key: str) -> None:
    st.markdown(r.answer)
    if r.tool == "budget" and access.form_url():
        st.markdown(f"👉 [**🔑 Request full access**]({access.form_url()}) to ask your own questions.")
    if r.needs_choice is not None:
        st.dataframe(r.needs_choice, hide_index=True, width="stretch")
    if r.model_card:
        mc = r.model_card
        st.warning(f"Model card · {mc['model']}: ROC-AUC **{mc['roc_auc']}**, base rate {mc['base_rate']}. "
                   f"{mc['interpretation']}", icon="⚠️")
    if r.data is not None and not r.data.empty:
        fig = auto_chart(r.data) if r.tool == "sql" else None
        if fig is not None:
            st.plotly_chart(fig, width="stretch", key=f"fig_{key}")
        with st.expander(f"Data ({len(r.data)} rows)"):
            st.dataframe(r.data, width="stretch", hide_index=True)
    if r.sql:
        with st.expander("Generated SQL"):
            st.code(r.sql, language="sql")
    st.caption(f"Tool: `{r.tool}`" + (f" · Sources: {', '.join(r.sources[:6])}" if r.sources else ""))


# ------------------------------------------------------------------ login
def login_page() -> None:
    wanted = st.query_params.get("role")
    brand("Role-aware, secure AI assistant for clinicians, administrators and business analysts.")

    if wanted not in ROLE_LABEL:
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown('<div class="cf-card"><div class="icon">🩺</div><h3>Clinician Assistant</h3>'
                        "<p>Patient history summaries, medications and allergies from medical reports, "
                        "cardiac history, readmission risk, clinical note search.</p></div>", unsafe_allow_html=True)
            if st.button("Continue as clinician", width="stretch", type="primary"):
                st.query_params["role"] = "clinician"
                st.rerun()
        with c2:
            st.markdown('<div class="cf-card"><div class="icon">📊</div><h3>Admin / BA Report Agent</h3>'
                        "<p>Natural-language analytics, claim-denial work queue, automated KPI reports with "
                        "AI commentary, audit log.</p></div>", unsafe_allow_html=True)
            if st.button("Continue as administrator", width="stretch", type="primary"):
                st.query_params["role"] = "admin"
                st.rerun()
        st.markdown('<p class="cf-sub" style="margin-top:14px">👀 <b>No account?</b> Choose an assistant, then '
                    '<b>Explore as guest</b> to try the pre-answered example questions.</p>', unsafe_allow_html=True)
        st.caption("Decision support only — not a diagnostic device. PHI is masked by role and every query is audited.")
        return

    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown(f'<span class="cf-badge">{ROLE_LABEL[wanted]}</span>', unsafe_allow_html=True)
        st.subheader("Sign in")
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", width="stretch")
        if ok:
            user = governance.authenticate(u, p)
            if user is None:
                st.error("Invalid username or password.")
            elif user["role"] != wanted:
                st.error(f"This account is not authorised for the {ROLE_LABEL[wanted]}.")
            else:
                governance.audit(user, "<login>", "auth")
                st.session_state.user = user
                st.session_state.history = []
                st.rerun()
        guest = guest_account(wanted)
        if guest:
            st.markdown('<div class="cf-divider" style="margin:14px 0 10px"></div>', unsafe_allow_html=True)
            if st.button("👀 Explore as guest — example questions only", width="stretch", key="guest"):
                governance.audit(guest, "<login guest>", "auth")
                st.session_state.user = guest
                st.session_state.history = []
                st.rerun()
        if st.button("← Choose a different assistant", width="stretch"):
            del st.query_params["role"]
            st.rerun()
        problem = governance.users_status()
        if problem:
            st.warning(problem, icon="🔑")


def guest_account(role: str) -> dict | None:
    """The cache-only guest account for this role, if it exists (python manage_users.py guest)."""
    name = f"guest.{role}"
    user = governance.load_users().get(name)
    if user and name in config.CACHE_ONLY_USERS and user["role"] == role:
        return {"username": name, "name": user["name"], "role": role}
    return None


def request_access_form(role: str, in_sidebar: bool = False) -> None:
    """Guests ask for a full trial account; the owner approves or rejects it.
    Uses a Google Form link if CIENMED_ACCESS_FORM_URL is set, otherwise the in-app GitHub form."""
    form_url = access.form_url()
    if form_url:
        st.link_button("🔑 Request full access", form_url, width="stretch",
                       help="Recruiter or reviewer? Ask for a trial account to ask your own questions.")
        return
    if not access.configured():
        return
    if st.session_state.get("access_requested"):
        st.success(f"Request #{st.session_state.access_requested} sent — you'll hear back by email.", icon="📨")
        return
    with st.expander("🔑 Request full access", expanded=False):
        st.caption("Recruiter or reviewer? Ask for a trial account to ask your own questions. "
                   "Your details are kept private and used only to reply.")
        with st.form(f"access_{'side' if in_sidebar else 'main'}", clear_on_submit=False):
            name = st.text_input("Name")
            email = st.text_input("Work email")
            org = st.text_input("Company / organisation")
            chosen = st.selectbox("Assistant", list(access.ROLES), index=list(access.ROLES).index(role),
                                  format_func=access.ROLES.get)
            reason = st.text_area("What would you like to explore? (optional)", max_chars=500)
            sent = st.form_submit_button("Send request", width="stretch")
        if sent:
            if st.session_state.get("access_attempts", 0) >= 3:
                st.error("Too many attempts in this session.")
                return
            st.session_state.access_attempts = st.session_state.get("access_attempts", 0) + 1
            try:
                number = access.submit_request(name, email, org, chosen, reason)
            except access.AccessError as e:
                st.error(str(e))
            else:
                st.session_state.access_requested = number
                governance.audit({"username": "_visitor", "role": chosen}, f"<access request #{number}>", "access")
                st.rerun()


# ------------------------------------------------------------------ sidebar
def sidebar(user: dict) -> None:
    with st.sidebar:
        st.markdown(f'<div class="cf-brand">{theme.LOGO_SVG.format(size=34)}'
                    f'<div><div class="t1" style="font-size:1.2rem">CienMed AI</div></div></div>',
                    unsafe_allow_html=True)
        st.markdown(f"**{user['name']}**  \n<span class='cf-badge'>{ROLE_LABEL[user['role']]}</span>",
                    unsafe_allow_html=True)
        st.caption(f"LLM: {'Euri · ' + config.LLM_MODEL if config.LLM_BACKEND == 'euri' else 'offline mock'}")
        if budget.is_cache_only(user["username"]):
            st.info("Demo account: example questions only (pre-answered).", icon="🔒")
            request_access_form(user["role"], in_sidebar=True)
        else:
            used, limit = budget.usage_today(user["username"]), budget.user_limit(user["username"])
            st.caption(f"AI calls today: {used} / {limit} (≈2 per new question; repeats are free)")
        if st.button("Clear conversation", width="stretch"):
            st.session_state.history = []
            st.rerun()
        if st.button("Sign out", width="stretch"):
            governance.audit(user, "<logout>", "auth")
            st.session_state.clear()
            st.query_params.clear()
            st.rerun()
        st.divider()
        st.caption("Decision support only — not a diagnostic device. PHI is masked by role and every query is audited.")


# ------------------------------------------------------------------ chat
def guest_banner(role: str) -> None:
    """Shown to demo/guest accounts: what they can do. The access request button lives in the sidebar."""
    st.info("**You're exploring the demo.** Click any example question below — answers are pre-generated. "
            "Want to ask your own questions? Use **🔑 Request full access** in the sidebar.", icon="👀")


def chat(user: dict, patient_id: int | None = None) -> None:
    role = user["role"]
    if budget.is_cache_only(user["username"]):
        guest_banner(role)
    cols = st.columns(3)
    for i, ex in enumerate(EXAMPLES[role]):
        if cols[i % 3].button(ex, key=f"ex{i}", width="stretch"):
            st.session_state.pending = ex

    for i, (q, r) in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant", avatar="🩺"):
            render_response(r, f"h{i}")

    q = st.chat_input("Ask CienMed AI…") or st.session_state.pop("pending", None)
    if q:
        with st.spinner("Thinking…"):
            r = orchestrator.answer(q, user, forced_patient_id=patient_id)
        st.session_state.history.append((q, r))
        st.rerun()   # redraw so the new answer appears in the history, above the input box


def clinician_page(user: dict) -> None:
    brand("Clinician Assistant · patient history, medications, allergies and risk — grounded in your records.")
    pid = st.number_input("Active patient ID (optional — pins every question to this patient)",
                          min_value=0, step=1, value=0)
    chat(user, int(pid) or None)


def admin_page(user: dict) -> None:
    brand("Admin / BA Report Agent · operations, finance and claims insight.")
    t_ask, t_rep, t_queue, t_audit = st.tabs(["💬 Ask", "📄 Report Agent", "🚩 Denial work queue", "🔒 Audit log"])
    with t_ask:
        chat(user)
    with t_rep:
        report_tab(user)
    with t_queue:
        df, mc = ml_tool.claim_denial_scores(limit=100)
        st.warning(f"Model ROC-AUC {mc['roc_auc']} (base rate {mc['base_rate']}). {mc['interpretation']}", icon="⚠️")
        st.dataframe(df, hide_index=True, width="stretch")
    with t_audit:
        st.dataframe(governance.read_audit(), hide_index=True, width="stretch")


def report_tab(user: dict) -> None:
    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
    kind = c1.selectbox("Report", list(reports.REPORT_TYPES),
                        help="\n".join(f"{k}: {v}" for k, v in reports.REPORT_TYPES.items()))
    start = c2.date_input("From", date(2024, 1, 1))
    end = c3.date_input("To", date(2024, 12, 31))
    facility = c4.selectbox("Facility", ["All facilities"] + _facilities())
    if st.button("Generate report", type="primary"):
        budget.set_user(user["username"])
        with st.spinner("Building report…"):
            rep = reports.build_report(kind, str(start), str(end), None if facility == "All facilities" else facility)
        governance.audit(user, f"<report> {kind}", "report", period=rep.period)
        st.session_state.report = rep

    rep = st.session_state.get("report")
    if not rep:
        st.caption("Choose a report and period, then Generate. Numbers come from fixed SQL; only the commentary is AI-written.")
        return
    st.markdown(f"#### {rep.title} · <span class='cf-badge'>{rep.period}</span>", unsafe_allow_html=True)
    for c, (k, v) in zip(st.columns(len(rep.kpis)), rep.kpis.items()):
        c.metric(k, v)
    with st.container(border=True):
        st.markdown("**🤖 AI commentary**")
        st.markdown(rep.narrative)
    fig_cols = st.columns(min(2, len(rep.figures)) or 1)
    for i, f in enumerate(rep.figures):
        f.update_layout(height=360)
        fig_cols[i % len(fig_cols)].plotly_chart(f, width="stretch", key=f"rep{i}")
    for name, df in rep.tables.items():
        with st.expander(name):
            st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Download report (Markdown)", rep.to_markdown(),
                       file_name=f"cienmed_{rep.title.lower().replace(' ', '_').replace('&', 'and')}.md")


@st.cache_data
def _facilities() -> list[str]:
    from cienmed import warehouse
    con = warehouse.connect()
    out = [r[0] for r in con.execute("SELECT DISTINCT facility_name FROM facility_metrics ORDER BY 1").fetchall()]
    con.close()
    return out


def main() -> None:
    user = st.session_state.get("user")
    if not user:
        login_page()
        return
    sidebar(user)
    (clinician_page if user["role"] == "clinician" else admin_page)(user)


main()