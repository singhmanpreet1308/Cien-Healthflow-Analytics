"""Access requests: a guest asks for a full account; the owner approves or rejects.

Requests are stored as issues in a PRIVATE GitHub repo (Streamlit Cloud's disk is wiped on restart,
and a private repo keeps requesters' emails out of public view). GitHub notifies the owner.

Option A — Google Form (simplest): CIENMED_ACCESS_FORM_URL = "https://forms.gle/..."
  The app shows a button to the form; approve with:  python manage_users.py trial <email> <role> "<Name>"

Option B — in-app form stored as GitHub issues. Settings (.env locally, Secrets on Streamlit Cloud):
  CIENMED_ACCESS_REPO   = "your-github-user/cienmed-access-requests"   (a PRIVATE repo)
  CIENMED_GITHUB_TOKEN  = fine-grained token with Issues: read & write on that repo only
"""
import os
import re

import requests

from cienmed import config  # noqa: F401  (loads .env so the settings below are visible)

API = "https://api.github.com"
LABEL_REQUEST, LABEL_APPROVED, LABEL_REJECTED = "access-request", "approved", "rejected"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
ROLES = {"clinician": "Clinician Assistant", "admin": "Admin / BA Report Agent"}


class AccessError(Exception):
    """Message is safe to show to the user."""


def _repo() -> str:
    return os.getenv("CIENMED_ACCESS_REPO", "").strip()


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('CIENMED_GITHUB_TOKEN', '').strip()}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def form_url() -> str:
    """Optional Google Form (or any https form) for access requests — no GitHub token needed."""
    url = os.getenv("CIENMED_ACCESS_FORM_URL", "").strip()
    return url if url.startswith("https://") else ""


def configured() -> bool:
    return bool(_repo() and os.getenv("CIENMED_GITHUB_TOKEN", "").strip())


def _call(method: str, path: str, **kw):
    resp = requests.request(method, f"{API}/repos/{_repo()}{path}", headers=_headers(), timeout=15, **kw)
    if resp.status_code >= 400:
        raise AccessError(f"GitHub API error {resp.status_code}: {resp.text[:150]}")
    return resp.json() if resp.content else {}


# ---------------------------------------------------------------- requester side (the app)
def validate(name: str, email: str, org: str, role: str, reason: str) -> dict:
    name, email, org, reason = (x.strip() for x in (name, email, org, reason))
    if not (2 <= len(name) <= 80):
        raise AccessError("Please enter your name.")
    if not EMAIL_RE.match(email) or len(email) > 120:
        raise AccessError("Please enter a valid email address.")
    if role not in ROLES:
        raise AccessError("Please choose an assistant.")
    if len(reason) > 500 or len(org) > 120:
        raise AccessError("Please keep the details shorter.")
    return {"name": name, "email": email.lower(), "org": org or "—", "role": role, "reason": reason or "—"}


def submit_request(name: str, email: str, org: str, role: str, reason: str) -> int:
    """Create the request issue. Returns the request number."""
    if not configured():
        raise AccessError("Access requests aren't enabled on this deployment.")
    r = validate(name, email, org, role, reason)
    body = (f"| Field | Value |\n|---|---|\n| Name | {r['name']} |\n| Email | {r['email']} |\n"
            f"| Organisation | {r['org']} |\n| Role | {r['role']} |\n| Reason | {r['reason']} |\n\n"
            f"Approve: `python manage_users.py approve <number>` · Reject: `python manage_users.py reject <number>`")
    issue = _call("POST", "/issues", json={"title": f"Access request: {r['name']} ({ROLES[r['role']]})",
                                           "body": body, "labels": [LABEL_REQUEST]})
    return int(issue["number"])


# ---------------------------------------------------------------- owner side (manage_users.py)
def parse_request(issue: dict) -> dict:
    fields = dict(re.findall(r"^\|\s*(Name|Email|Organisation|Role|Reason)\s*\|\s*(.*?)\s*\|$",
                             issue.get("body") or "", re.M))
    return {"number": issue["number"], "name": fields.get("Name", ""), "email": fields.get("Email", ""),
            "org": fields.get("Organisation", ""), "role": fields.get("Role", ""),
            "reason": fields.get("Reason", ""), "created": issue.get("created_at", "")[:10]}


def open_requests() -> list[dict]:
    issues = _call("GET", "/issues", params={"state": "open", "labels": LABEL_REQUEST, "per_page": 50})
    return [parse_request(i) for i in issues]


def get_request(number: int) -> dict:
    issue = _call("GET", f"/issues/{number}")
    if LABEL_REQUEST not in {lbl["name"] for lbl in issue.get("labels", [])}:
        raise AccessError(f"#{number} is not an access request.")
    if issue.get("state") != "open":
        raise AccessError(f"#{number} is already closed.")
    return parse_request(issue)


def close_request(number: int, label: str, comment: str) -> None:
    """Comment (never containing a password), label and close the request."""
    _call("POST", f"/issues/{number}/comments", json={"body": comment})
    _call("POST", f"/issues/{number}/labels", json={"labels": [label]})
    _call("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})