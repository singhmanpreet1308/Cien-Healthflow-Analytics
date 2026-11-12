"""Governance layer: authentication, role-based PHI masking, audit logging."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone

import bcrypt
import pandas as pd
import yaml

from cienmed import config

PHI_COLUMNS = {"first_name", "last_name", "phone", "email", "date_of_birth"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\b\d{10}\b")


# ---------------- Authentication ----------------
def _users_yaml_text() -> tuple[str, str]:
    """Return (yaml_text, source). Order: users.yaml file -> env var -> Streamlit secrets."""
    if config.USERS_FILE.exists():
        return config.USERS_FILE.read_text(encoding="utf-8"), "users.yaml"
    text = os.getenv("CIENMED_USERS_YAML", "")
    if text.strip():
        return text, "environment"
    try:  # Streamlit Cloud: read the secret directly as well
        import streamlit as st
        text = st.secrets.get("CIENMED_USERS_YAML", "")
        if text.strip():
            return text, "streamlit secrets"
    except Exception:
        pass
    return "", "none"


def load_users() -> dict:
    """Accounts come from users.yaml locally, or from the CIENMED_USERS_YAML secret when deployed
    (users.yaml is never committed). Passwords are bcrypt hashes in both cases."""
    text, _ = _users_yaml_text()
    if not text.strip():
        return {}
    try:
        return (yaml.safe_load(text) or {}).get("users", {}) or {}
    except yaml.YAMLError:
        return {}


def users_status() -> str:
    """Human-readable reason when no accounts load (shown on the login page, no secrets revealed)."""
    text, source = _users_yaml_text()
    if source == "none":
        return "No accounts found: add the CIENMED_USERS_YAML secret (python manage_users.py secrets), or run python manage_users.py demo locally."
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        return f"CIENMED_USERS_YAML from {source} is not valid YAML (check indentation): {str(e).splitlines()[0]}"
    if not (data.get("users") or {}):
        return f"CIENMED_USERS_YAML from {source} has no users under 'users:'."
    return ""


def is_expired(user: dict) -> bool:
    """Trial accounts carry `expires: YYYY-MM-DD` (last valid day). No field = never expires."""
    exp = user.get("expires")
    if not exp:
        return False
    try:
        return date.fromisoformat(str(exp)) < date.today()
    except ValueError:
        return True          # unreadable date: fail closed


def user_daily_limit(username: str) -> int | None:
    """Per-account daily paid-call limit (`daily_limit` in users.yaml), or None for the global default."""
    limit = load_users().get((username or "").strip().lower(), {}).get("daily_limit")
    return int(limit) if limit is not None else None


def authenticate(username: str, password: str) -> dict | None:
    """Return {'username', 'name', 'role'} on success, else None (also None for expired accounts)."""
    user = load_users().get(username.strip().lower())
    if not user:
        bcrypt.checkpw(b"x", bcrypt.hashpw(b"y", bcrypt.gensalt()))  # constant-ish time on unknown user
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()) and not is_expired(user):
        return {"username": username.strip().lower(), "name": user["name"], "role": user["role"]}
    return None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


# ---------------- PHI masking ----------------
def _pseudo(value) -> str:
    return "PT-" + hashlib.sha256(str(value).encode()).hexdigest()[:8]


def mask_df(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """Admins never see direct identifiers; clinicians see everything except contact details."""
    if df is None or df.empty:
        return df
    out = df.copy()
    hide = PHI_COLUMNS if role == "admin" else {"phone", "email"}
    for col in out.columns:
        if col.lower() in hide:
            out[col] = out[col].map(_pseudo) if col.lower() in {"first_name", "last_name"} else "***"
    return out


def mask_text(text: str, role: str) -> str:
    text = EMAIL_RE.sub("[email]", text)
    text = PHONE_RE.sub("[phone]", text)
    return text


# ---------------- Audit ----------------
def audit(user: dict, question: str, tool: str, **details) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": user.get("username"), "role": user.get("role"),
        "question": question, "tool": tool,
        **{k: v for k, v in details.items() if v is not None},
    }
    with open(config.AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def read_audit(n: int = 200) -> pd.DataFrame:
    if not config.AUDIT_LOG.exists():
        return pd.DataFrame()
    lines = config.AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    return pd.DataFrame([json.loads(x) for x in lines]).iloc[::-1]