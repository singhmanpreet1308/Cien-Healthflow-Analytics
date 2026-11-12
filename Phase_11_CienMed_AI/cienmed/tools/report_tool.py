"""Medical history PDF reports: extract text, split into sections, read the medication table.

Files live in data/docs/medical_reports/ and are named medical_history_<patient_id>.pdf,
so each report is linked to its patient straight from the filename.
"""
import re
from functools import lru_cache

import pandas as pd
import pdfplumber

from cienmed import config

SECTIONS = ["History", "Diagnoses", "Medications", "Allergies", "Surgeries and Procedures", "Recent Encounters"]
_SECTION_RE = re.compile(r"^(" + "|".join(re.escape(s) for s in SECTIONS) + r")\s*$", re.M)
_FILE_RE = re.compile(r"medical_history_(\d+)\.pdf$", re.I)

MED_COLUMNS = ["medication", "form", "dose", "start", "end", "status"]
# Fallback when the PDF table has no detectable borders: one medication per text line
_MED_LINE = re.compile(
    r"^(?P<medication>.+?)\s+(?P<form>Tablet|Capsule|Inhaler|Injection|Syrup|Cream|Ointment|Drops|Spray|Patch|"
    r"Suspension|Solution|Gel|Powder)\s+(?P<dose>.+?)\s+(?P<start>\d{1,2} \w{3} \d{4})\s+"
    r"(?P<end>\d{1,2} \w{3} \d{4}|-)\s+(?P<status>\w[\w ]*)$",
    re.I,
)


def report_files() -> dict[int, "Path"]:
    """{patient_id: path} for every report in the folder."""
    out = {}
    for path in sorted(config.REPORTS_DIR.glob("*.pdf")):
        m = _FILE_RE.search(path.name)
        if m:
            out[int(m.group(1))] = path
    return out


@lru_cache(maxsize=256)
def _read(path_str: str) -> tuple[str, list]:
    """Full text + all tables of a PDF (cached so each file is parsed once)."""
    text, tables = [], []
    with pdfplumber.open(path_str) as pdf:
        for page in pdf.pages:
            text.append(page.extract_text() or "")
            tables.extend(page.extract_tables() or [])
    return "\n".join(text), tables


def sections(patient_id: int) -> dict[str, str]:
    """{'History': '...', 'Medications': '...', ...} for one patient, or {} if no report."""
    path = report_files().get(patient_id)
    if not path:
        return {}
    text, _ = _read(str(path))
    parts = _SECTION_RE.split(text)
    # parts = [header, 'History', body, 'Diagnoses', body, ...]
    out = {"Header": parts[0].strip()}
    for name, body in zip(parts[1::2], parts[2::2]):
        out[name] = body.strip()
    return out


def medications(patient_id: int) -> pd.DataFrame | None:
    """Actual medications from the report (None if the patient has no report)."""
    path = report_files().get(patient_id)
    if not path:
        return None
    _, tables = _read(str(path))

    # 1) Preferred: a real table whose header starts with Medication ... Dose
    for t in tables:
        header = [str(c or "").strip().lower() for c in t[0]]
        if header[:1] == ["medication"] and "dose" in header:
            rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t[1:] if any(r)]
            return pd.DataFrame(rows, columns=MED_COLUMNS[: len(header)])

    # 2) Fallback: parse the Medications section line by line
    body = sections(patient_id).get("Medications", "")
    rows = [m.groupdict() for line in body.splitlines()[1:] if (m := _MED_LINE.match(line.strip()))]
    return pd.DataFrame(rows, columns=MED_COLUMNS)

_ALLERGY_LINE = re.compile(r"^(?P<allergen>.+?)\s+[-–]\s+(?P<reaction>.+?)\s*\((?P<severity>[^)]+)\)\.?$")


def allergies(patient_id: int) -> pd.DataFrame | None:
    """Structured allergies from the report. Empty DataFrame = 'None known'; None = no report."""
    if patient_id not in report_files():
        return None
    body = sections(patient_id).get("Allergies", "").strip()
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("none"):
            continue
        m = _ALLERGY_LINE.match(line)
        # If a line doesn't match the pattern, keep it as-is — never silently drop an allergy
        rows.append(m.groupdict() if m else {"allergen": line, "reaction": "", "severity": ""})
    return pd.DataFrame(rows, columns=["allergen", "reaction", "severity"])


def all_allergies() -> pd.DataFrame:
    """One row per (patient, allergy) across every report — for 'which patients are allergic to X?'."""
    frames = []
    for pid in report_files():
        df = allergies(pid)
        if df is not None and not df.empty:
            frames.append(df.assign(patient_id=pid))
    cols = ["patient_id", "allergen", "reaction", "severity"]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)
