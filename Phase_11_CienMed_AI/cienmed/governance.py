"""Governance layer: authentication, role-based PHI masking, audit logging."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import bcrypt
import pandas as pd
import yaml

from cienmed import config

PHI_COLUMNS = {"first_name", "last_name", "phone", "email", "date_of_birth"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\b\d{10}\b")


# ---------------- Authentication ----------------
def load_users() -> dict:
    if not config.USERS_FILE.exists():
        return {}
    return yaml.safe_load(config.USERS_FILE.read_text()).get("users", {})


def authenticate(username: str, password: str) -> dict | None:
    """Return {'username', 'name', 'role'} on success, else None."""
    user = load_users().get(username.strip().lower())
    if not user:
        bcrypt.checkpw(b"x", bcrypt.hashpw(b"y", bcrypt.gensalt()))  # constant-ish time on unknown user
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {"username": username.strip().lower(), "name": user["name"], "role": user["role"]}
    return None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


# ---------------- PHI masking ----------------
def _pseudo(value) -> str:
    """Salted hash: stable inside this system, not reversible without the secret salt."""
    return "PT-" + hashlib.sha256(f"{config.PHI_SALT}|{value}".encode()).hexdigest()[:8]


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