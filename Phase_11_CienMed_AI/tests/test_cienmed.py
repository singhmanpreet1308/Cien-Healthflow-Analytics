"""CienMed AI — automated tests. Fully offline: zero API tokens.

Run from Phase_11_CienMed_AI:   pytest -q
"""
import os

os.environ["CIENMED_LLM"] = "mock"          # must be set before cienmed is imported

import json
from pathlib import Path

import pandas as pd
import pytest

from cienmed import budget, config, governance, llm, orchestrator, reports, warehouse
from cienmed.tools import ml_tool, patient_tool, rag_tool, report_tool, sql_tool

DOC = {"username": "t.doc", "role": "clinician"}
ADM = {"username": "t.adm", "role": "admin"}
APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


# ---------------------------------------------------------------- warehouse (Step 2)
def test_warehouse_row_counts():
    con = warehouse.connect()
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("patients", "claims", "diagnoses", "providers", "facility_metrics")}
    con.close()
    assert counts == {"patients": 20000, "claims": 50000, "diagnoses": 30000,
                      "providers": 500, "facility_metrics": 720}


def test_data_quality_fixes():
    con = warehouse.connect()
    assert con.execute("SELECT count(*) FROM patients WHERE phone LIKE '-%'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM patients WHERE insurance_provider IS NULL").fetchone()[0] == 0
    con.close()


# ---------------------------------------------------------------- SQL guardrails (Step 4)
@pytest.mark.parametrize("sql", ["DROP TABLE claims", "SELECT 1; DELETE FROM claims",
                                 "INSERT INTO claims VALUES (1)", "SELECT * FROM facility_metrics"])
def test_sql_guardrails_block(sql):
    with pytest.raises(PermissionError):
        sql_tool.validate(sql, "clinician")


def test_sql_allows_cte():
    assert len(sql_tool.run_sql("WITH t AS (SELECT * FROM v_insurer_denials) SELECT * FROM t", "admin")) == 8


def test_out_of_scope_concept_refused_before_llm():
    r = sql_tool.ask("Which facilities have the longest average wait time?", "clinician")
    assert r.attempts == 0 and "facility operations" in r.error
    assert sql_tool.concept_block("Which facilities have the longest average wait time?", "admin") is None


def test_both_conditions_ground_truth():
    """The 'AND on the same row' trap: CKD 3 + pneumonia must be 49 patients, not 0."""
    df = sql_tool.run_sql("""SELECT count(*) n FROM (SELECT patient_id FROM diagnoses GROUP BY 1
                             HAVING bool_or(diagnosis_code='N18.3') AND bool_or(diagnosis_code='J18.9'))""", "clinician")
    assert df.n[0] == 49


# ---------------------------------------------------------------- patient + reports (Steps 5, 6b)
def test_patient_lookup_and_injection():
    assert patient_tool.get_patient(999999) is None
    assert patient_tool.find_patients("x' OR 1=1 --").empty
    assert len(patient_tool.find_patients("Aryan")) > 1


def test_allergy_unknown_vs_none():
    assert report_tool.allergies(12224) is None             # no report -> UNKNOWN
    with_reports = list(report_tool.report_files())
    if not with_reports:
        pytest.skip("no PDF reports in data/docs/medical_reports")
    assert isinstance(report_tool.allergies(with_reports[0]), pd.DataFrame)


def test_no_report_allergy_answer_never_guesses():
    r = orchestrator.answer("Does patient 12224 have any allergies?", DOC)
    assert "UNKNOWN" in r.answer


# ---------------------------------------------------------------- RAG (Step 6)
def test_admin_never_sees_patient_notes_or_reports():
    hits = rag_tool.retrieve("chronic kidney disease pneumonia allergy medication", "admin", k=10)
    assert all(c.audience == "all" for c, _ in hits)


def test_rag_drops_weak_matches():
    assert all(score >= rag_tool.MIN_SCORE for _, score in rag_tool.retrieve("readmission", "admin"))


# ---------------------------------------------------------------- ML (Step 7)
def test_model_cards_are_honest():
    for card in ml_tool.model_cards():
        assert 0.3 < card["roc_auc"] < 0.7 and "split" in card and "interpretation" in card
    assert ml_tool.patient_readmission_risk(5) is None       # no diagnoses -> no score


# ---------------------------------------------------------------- governance (Step 8)
def test_phi_masking_by_role():
    df = pd.DataFrame({"first_name": ["Asha"], "email": ["a@b.com"], "date_of_birth": ["1990-01-01"]})
    adm, doc = governance.mask_df(df, "admin"), governance.mask_df(df, "clinician")
    assert adm.first_name[0].startswith("PT-") and adm.date_of_birth[0] == "***"
    assert doc.first_name[0] == "Asha" and doc.email[0] == "***"
    assert governance.mask_text("mail a@b.com or 9876543210", "admin") == "mail [email] or [phone]"


def test_users_can_come_from_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "missing.yaml")
    hashed = governance.hash_password("pw")
    monkeypatch.setenv("CIENMED_USERS_YAML", f"users:\n  x.y:\n    name: X\n    role: admin\n    password_hash: '{hashed}'\n")
    assert governance.authenticate("x.y", "pw")["role"] == "admin"


# ---------------------------------------------------------------- orchestrator (Step 9)
def test_role_separation():
    assert orchestrator.answer("Summarise patient 3's medical history", DOC).tool == "patient_summary"
    r = orchestrator.answer("Summarise patient 3's medical history", ADM)
    assert r.tool in orchestrator.ROLE_TOOLS["admin"] and "aren't available" in r.answer


def test_ambiguous_name_asks_instead_of_guessing():
    r = orchestrator.answer("Summarise Aryan's history", DOC)
    assert r.needs_choice is not None and len(r.needs_choice) > 1


# ---------------------------------------------------------------- reports (Step 10)
def test_reports_are_reproducible():
    a = reports.build_report("Claims & denials", "2024-01-01", "2024-12-31")
    b = reports.build_report("Claims & denials", "2024-01-01", "2024-12-31")
    assert a.kpis == b.kpis and a.kpis["Claims"] == "16,607"
    for kind in reports.REPORT_TYPES:
        assert reports.build_report(kind, "2024-01-01", "2024-12-31").figures


def test_llm_gets_formatted_money_and_full_tables():
    df = reports._for_llm(pd.DataFrame({"facility_name": ["A"], "revenue": [221277668]}))
    assert df.revenue[0] == "₹22.13 Cr"


# ---------------------------------------------------------------- token budget (Step 11b)
class _CountingLLM:
    calls = 0

    def chat(self, system, user):
        _CountingLLM.calls += 1
        return llm.MockLLM().chat(system, user)


@pytest.fixture
def paid_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LLM_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(config, "DEMO_CACHE_PATH", tmp_path / "demo.json")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "USER_DAILY_LIMIT", 4)
    _CountingLLM.calls = 0
    cached = llm.CachedLLM(_CountingLLM(), "test-model")
    llm.set_llm(cached)
    yield cached
    llm.set_llm(llm.MockLLM())


def test_guest_never_spends_tokens(paid_llm):
    r = orchestrator.answer("What medications is patient 1 taking?", {"username": "guest.clinician", "role": "clinician"})
    assert r.tool == "budget" and _CountingLLM.calls == 0


def test_daily_limit_and_free_repeats(paid_llm):
    for pid in (1, 2):                                       # 2 calls each -> limit of 4 reached
        orchestrator.answer(f"What medications is patient {pid} taking?", DOC)
    assert budget.usage_today("t.doc") == 4
    assert orchestrator.answer("What medications is patient 4000 taking?", DOC).tool == "budget"
    calls = _CountingLLM.calls
    assert orchestrator.answer("What medications is patient 1 taking?", DOC).tool == "medications"
    assert _CountingLLM.calls == calls                       # repeat came from cache: free


def test_demo_cache_serves_guests(paid_llm):
    orchestrator.answer("What medications is patient 1 taking?", {"username": "_system", "role": "clinician"})
    config.DEMO_CACHE_PATH.write_text(json.dumps(paid_llm.cache))
    fresh = llm.CachedLLM(_CountingLLM(), "test-model")     # like a Streamlit Cloud restart
    fresh.cache = {}
    llm.set_llm(fresh)
    r = orchestrator.answer("What medications is patient 1 taking?", {"username": "guest.clinician", "role": "clinician"})
    assert r.tool == "medications"


# ---------------------------------------------------------------- UI (Step 11)
def _login(role, username, password):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["role"] = role
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click().run()
    return at


@pytest.fixture
def demo_users(monkeypatch, tmp_path):
    import yaml
    users = {"a.admin": {"name": "A", "role": "admin", "password_hash": governance.hash_password("pw")},
             "guest.clinician": {"name": "G", "role": "clinician", "password_hash": governance.hash_password("x")}}
    f = tmp_path / "users.yaml"
    f.write_text(yaml.safe_dump({"users": users}))
    monkeypatch.setattr(config, "USERS_FILE", f)


def test_ui_admin_login(demo_users):
    at = _login("admin", "a.admin", "pw")
    assert not at.exception and any("Report Agent" in t.label for t in at.tabs)


def test_ui_wrong_role_rejected(demo_users):
    at = _login("clinician", "a.admin", "pw")
    assert any("not authorised" in e.value for e in at.error)


def test_ui_one_click_guest(demo_users):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["role"] = "clinician"
    at.run()
    next(b for b in at.button if "guest" in b.label.lower()).click().run()
    assert not at.exception and any("Demo account" in i.value for i in at.info)


# ---------------------------------------------------------------- access requests (Step 13)
class _FakeGitHub:
    """In-memory stand-in for the GitHub Issues API."""

    def __init__(self):
        self.issues, self.comments = {}, {}

    def __call__(self, method, url, headers=None, timeout=None, json=None, params=None):
        import re as _re
        path = url.split("/repos/owner/requests", 1)[1]

        class R:
            def __init__(self, data, code=200):
                self._d, self.status_code, self.content, self.text = data, code, b"x", ""

            def json(self):
                return self._d
        if method == "POST" and path == "/issues":
            n = len(self.issues) + 1
            self.issues[n] = {"number": n, "body": json["body"], "state": "open", "created_at": "2026-11-12T10:00:00Z",
                              "labels": [{"name": lbl} for lbl in json["labels"]]}
            return R(self.issues[n], 201)
        if method == "GET" and path == "/issues":
            return R([i for i in self.issues.values() if i["state"] == "open"])
        m = _re.match(r"/issues/(\d+)(/comments|/labels)?$", path)
        issue = self.issues[int(m.group(1))]
        if m.group(2) == "/comments":
            self.comments.setdefault(issue["number"], []).append(json["body"])
        elif m.group(2) == "/labels":
            issue["labels"] += [{"name": lbl} for lbl in json["labels"]]
        elif method == "PATCH":
            issue["state"] = json["state"]
        return R(issue)


@pytest.fixture
def github(monkeypatch, tmp_path):
    from cienmed import access
    fake = _FakeGitHub()
    monkeypatch.setattr(access.requests, "request", fake)
    monkeypatch.setenv("CIENMED_ACCESS_REPO", "owner/requests")
    monkeypatch.setenv("CIENMED_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "users.yaml")
    return fake


def test_access_request_validation(github):
    from cienmed import access
    with pytest.raises(access.AccessError):
        access.submit_request("Jo Smith", "not-an-email", "Acme", "admin", "")
    with pytest.raises(access.AccessError):
        access.submit_request("Jo Smith", "jo@acme.com", "Acme", "superuser", "")


def test_approve_creates_expiring_limited_account(github, capsys):
    import manage_users
    from cienmed import access
    n = access.submit_request("Jo Smith", "Jo.Smith@acme.com", "Acme Health", "admin", "Hiring for AI engineer")
    assert [r["email"] for r in access.open_requests()] == ["jo.smith@acme.com"]

    manage_users.main(["approve", str(n), "7"])
    out = capsys.readouterr().out
    password = out.split("Password:")[1].split()[0]

    user = governance.authenticate("jo.smith", password)
    assert user == {"username": "jo.smith", "name": "Jo Smith", "role": "admin"}
    stored = governance.load_users()["jo.smith"]
    assert stored["daily_limit"] == manage_users.TRIAL_DAILY_LIMIT and stored["expires"]
    assert github.issues[n]["state"] == "closed"
    assert all(password not in c for c in github.comments[n])          # password never written to GitHub
    assert access.open_requests() == []


def test_expired_account_cannot_log_in(github):
    import yaml
    config.USERS_FILE.write_text(yaml.safe_dump({"users": {"old.user": {
        "name": "Old", "role": "admin", "password_hash": governance.hash_password("pw"), "expires": "2020-01-01"}}}))
    assert governance.authenticate("old.user", "pw") is None


def test_reject_closes_without_account(github):
    import manage_users
    from cienmed import access
    n = access.submit_request("Sam Lee", "sam@example.org", "", "clinician", "")
    manage_users.main(["reject", str(n), "Not hiring for clinical roles"])
    assert github.issues[n]["state"] == "closed" and governance.load_users() == {}
    assert any(lbl["name"] == "rejected" for lbl in github.issues[n]["labels"])


def test_ui_request_form_submits(demo_users, github, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("CIENMED_ACCESS_FORM_URL", raising=False)   # a local .env form URL hides the in-app form
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["role"] = "clinician"
    at.run()
    next(b for b in at.button if "guest" in b.label.lower()).click().run()   # form lives in the guest sidebar
    ti = {t.label: t for t in at.text_input}
    ti["Name"].input("Jo Smith"); ti["Work email"].input("jo@acme.com"); ti["Company / organisation"].input("Acme")
    next(b for b in at.button if b.label == "Send request").click().run()
    assert not at.exception and any("Request #1 sent" in s.value for s in at.success)
    assert len(github.issues) == 1


def test_trial_command_for_google_form_requests(monkeypatch, tmp_path, capsys):
    import manage_users
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "users.yaml")
    manage_users.main(["trial", "Jo.Smith@Acme.com", "clinician", "Jo Smith", "3"])
    password = capsys.readouterr().out.split("Password:")[1].split()[0]
    assert governance.authenticate("jo.smith", password)["role"] == "clinician"
    assert governance.load_users()["jo.smith"]["daily_limit"] == manage_users.TRIAL_DAILY_LIMIT


def test_ui_google_form_button(demo_users, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("CIENMED_ACCESS_FORM_URL", "https://forms.gle/example")
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["role"] = "admin"
    at.run()
    assert not at.exception
    assert not any(b.label == "Send request" for b in at.button)       # form link replaces in-app form


def test_extend_and_limit_commands(monkeypatch, tmp_path, capsys):
    import yaml
    import manage_users
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "users.yaml")
    config.USERS_FILE.write_text(yaml.safe_dump({"users": {"jo": {
        "name": "Jo", "role": "admin", "password_hash": governance.hash_password("pw"), "expires": "2020-01-01"}}}))
    assert governance.authenticate("jo", "pw") is None                 # expired
    manage_users.main(["extend", "jo", "5"])
    assert governance.authenticate("jo", "pw") is not None             # re-opened
    manage_users.main(["limit", "jo", "10"])
    assert governance.user_daily_limit("jo") == 10


def test_ui_guest_banner_offers_access(demo_users, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("CIENMED_ACCESS_FORM_URL", "https://forms.gle/example")
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["role"] = "clinician"
    at.run()
    next(b for b in at.button if "guest" in b.label.lower()).click().run()
    assert not at.exception and any("exploring the demo" in i.value for i in at.info)