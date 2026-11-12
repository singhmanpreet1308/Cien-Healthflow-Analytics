"""RAG knowledge base: Extract -> Clean -> Chunk -> Vectorise -> Store -> Retrieve.

Corpus
  * Knowledge docs in data/docs/*.md (data dictionary, governance policy) — any role
  * Generated clinical notes, one per patient, built from diagnoses — clinician only
"""
import re
from dataclasses import asdict, dataclass

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from cienmed import config, warehouse
from cienmed.tools import report_tool

MIN_SCORE = 0.05 

@dataclass
class Chunk:
    id: str
    text: str
    source: str
    audience: str              # "all" or "clinician" — used for role filtering
    patient_id: int | None = None


def _doc_chunks() -> list[Chunk]:
    """Split each .md doc into one chunk per '## ' section."""
    chunks = []
    for path in sorted(config.DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = ""
        for i, section in enumerate(re.split(r"\n(?=## )", text)):
            section = section.strip()
            if section.startswith("# "):                      # document title line
                title = section.splitlines()[0][2:]
                section = "\n".join(section.splitlines()[1:]).strip()
            if section:
                chunks.append(Chunk(f"{path.stem}#{i}", f"{title}\n{section}", path.name, "all"))
    return chunks


def _patient_note_chunks() -> list[Chunk]:
    """No medical reports exist, so build one clinical note per patient from diagnoses."""
    con = warehouse.connect()
    df = con.execute(
        """
        SELECT patient_id,
               string_agg(strftime(diagnosis_date, '%Y-%m-%d') || ' ' || diagnosis_description
                          || ' (' || diagnosis_code || ', ' || severity
                          || CASE WHEN is_chronic THEN ', chronic' ELSE '' END || '; '
                          || treatment_plan || '; seen by ' || specialization || ')',
                          '. ' ORDER BY diagnosis_date) AS history
        FROM v_patient_diagnoses
        GROUP BY patient_id
        """
    ).df()
    con.close()
    return [
        Chunk(f"note#{r.patient_id}", f"Clinical note, patient {r.patient_id}. History: {r.history}.",
              "generated_patient_notes", "clinician", int(r.patient_id))
        for r in df.itertuples()
    ]

def _report_chunks() -> list[Chunk]:
    """One chunk per section of each PDF medical report — clinician only (PHI)."""
    chunks = []
    for pid in report_tool.report_files():
        for name, body in report_tool.sections(pid).items():
            if name == "Header" or not body:
                continue
            chunks.append(Chunk(f"report#{pid}#{name}",
                                f"Medical history report, patient {pid}, section {name}:\n{body}",
                                f"medical_history_{pid}.pdf", "clinician", pid))
    return chunks



def build_index() -> dict:
    chunks =  _doc_chunks() + _report_chunks() + _patient_note_chunks()
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    matrix = vec.fit_transform([c.text for c in chunks])
    # Save chunks as plain dicts so the file loads from any script
    joblib.dump({"vectorizer": vec, "matrix": matrix, "chunks": [asdict(c) for c in chunks]},
                config.RAG_INDEX_PATH)
    return {"vectorizer": vec, "matrix": matrix, "chunks": chunks}


_INDEX: dict | None = None


def _index() -> dict:
    """Load the saved index once; build it if it doesn't exist yet."""
    global _INDEX
    if _INDEX is None:
        if config.RAG_INDEX_PATH.exists():
            _INDEX = joblib.load(config.RAG_INDEX_PATH)
            _INDEX["chunks"] = [Chunk(**c) for c in _INDEX["chunks"]]
        else:
            _INDEX = build_index()
    return _INDEX


def retrieve(query: str, role: str, k: int = 5) -> list[tuple[Chunk, float]]:
    idx = _index()
    sims = cosine_similarity(idx["vectorizer"].transform([query]), idx["matrix"])[0]
    # Role filter: admins never see patient notes
    allowed = np.array([c.audience == "all" or role == "clinician" for c in idx["chunks"]])
    sims = np.where(allowed, sims, -1)
    top = np.argsort(-sims)[:k]
    return [(idx["chunks"][i], float(sims[i])) for i in top if sims[i] >= MIN_SCORE]


if __name__ == "__main__":
    ix = build_index()
    print(f"Indexed {len(ix['chunks']):,} chunks")