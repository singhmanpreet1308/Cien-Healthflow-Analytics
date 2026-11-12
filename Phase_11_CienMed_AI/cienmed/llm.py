"""LLM layer: Euri (OpenAI-compatible) + disk cache + token budget + offline mock.

get_llm() returns:
  * CIENMED_LLM=mock  -> MockLLM (offline, zero tokens)
  * otherwise         -> CachedLLM(EuriLLM): identical prompts are answered from the cache for free;
                         a cache miss is checked against the token budget before Euri is called.
"""
import hashlib
import json
import re
from typing import Protocol

from cienmed import budget, config


class LLM(Protocol):
    def chat(self, system: str, user: str) -> str: ...


class EuriLLM:
    def __init__(self, model: str = config.LLM_MODEL):
        from openai import OpenAI

        if not config.EURI_API_KEY:
            raise RuntimeError("EURI_API_KEY is not set in .env (or set CIENMED_LLM=mock).")
        self.client = OpenAI(api_key=config.EURI_API_KEY, base_url=config.EURI_BASE_URL)
        self.model = model

    def chat(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


class CachedLLM:
    """Same model + same prompts = saved answer, no API call.

    Two caches are read: the committed demo cache (pre-answered example questions, read-only)
    and the local cache that grows as you use the app. New answers go to the local cache.
    """

    def __init__(self, inner, model: str):
        self.inner, self.model = inner, model
        self.cache = self._read(config.LLM_CACHE_PATH)
        self.demo = self._read(config.DEMO_CACHE_PATH)
        self.hits = self.misses = 0
        self.used_keys: set[str] = set()   # lets build_demo_cache.py collect the example answers

    @staticmethod
    def _read(path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def key(self, system: str, user: str) -> str:
        return hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()

    def lookup(self, key: str) -> str | None:
        return self.cache.get(key) or self.demo.get(key)

    def chat(self, system: str, user: str) -> str:
        k = self.key(system, user)
        self.used_keys.add(k)
        cached = self.lookup(k)
        if cached is not None:
            self.hits += 1
            return cached
        budget.check_and_spend()            # raises BudgetExceeded instead of spending tokens
        self.misses += 1
        reply = self.inner.chat(system, user)
        self.cache[k] = reply
        config.LLM_CACHE_PATH.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
        return reply

    def stats(self) -> str:
        return f"LLM cache: {self.hits} free (cached), {self.misses} paid API calls"


class MockLLM:
    """Deterministic stand-in so the whole pipeline runs without an API key.

    It recognises the prompt type by a marker in the system prompt and returns
    a plausible structured answer. Good enough for tests and a no-key demo.
    """

    def chat(self, system: str, user: str) -> str:
        q = user.lower()
        if "[ROUTER]" in system:
            return json.dumps(_mock_route(q))
        if "[TEXT2SQL]" in system:
            return _mock_sql(q)
        # Synthesis / summary prompts: echo the grounded context compactly
        ctx = user.split("CONTEXT:", 1)[-1].strip()
        return ("_Offline mock answer — set `EURI_API_KEY` for real LLM output. Grounded context:_\n\n```text\n"
                + ctx[:1500] + "\n```")


def _mock_route(q: str) -> dict:
    m = re.search(r"patient\s*(?:id\s*)?#?(\d+)", q)
    pid = int(m.group(1)) if m else None
    name = re.search(r"summari[sz]e ([a-z]+(?: [a-z]+)?)'s", q)
    if not pid and name:
        return {"tool": "patient_summary", "args": {"patient_name": name.group(1)}}
    if "allerg" in q:
        return {"tool": "allergies", "args": {"patient_id": pid}} if pid else {"tool": "allergy_search", "args": {}}
    if pid and any(w in q for w in ("medication", "drug", "taking")):
        return {"tool": "medications", "args": {"patient_id": pid}}
    if pid and "cardiac" in q:
        return {"tool": "cardiac_history", "args": {"patient_id": pid}}
    if any(w in q for w in ("risk", "predict", "likely")):
        return {"tool": "ml", "args": {"patient_id": pid, "task": "readmission" if pid else "claim_denial"}}
    if pid:
        return {"tool": "patient_summary", "args": {"patient_id": pid}}
    if any(w in q for w in ("policy", "definition", "dictionary", "what does", "how is")):
        return {"tool": "rag", "args": {"query": q}}
    return {"tool": "sql", "args": {"question": q}}


def _mock_sql(q: str) -> str:
    if "insurer" in q or "denial" in q:
        return "SELECT insurance_provider, denial_rate_pct, total_claims FROM v_insurer_denials ORDER BY denial_rate_pct DESC"
    if "service" in q:
        return ("SELECT service_type, sum(billed_amount) AS billed FROM v_claims_enriched "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
    if "facility" in q or "wait" in q:
        return ("SELECT facility_name, round(avg(avg_wait_time_minutes),1) AS avg_wait FROM facility_metrics "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 10")
    return ("SELECT strftime(claim_month, '%Y-%m') AS month, count(*) AS claims FROM v_claims_enriched "
            "GROUP BY 1 ORDER BY 1")



_llm: LLM | None = None


def get_llm() -> LLM:
    """Every module calls this. Created once and reused."""
    global _llm
    if _llm is None:
        if config.LLM_BACKEND == "euri":
            real = EuriLLM()
            _llm = CachedLLM(real, real.model) if config.LLM_CACHE else real
        else:
            _llm = MockLLM()
    return _llm


def set_llm(llm: LLM) -> None:
    global _llm
    _llm = llm


def parse_json(text: str) -> dict:
    """Pull the first {...} out of an LLM reply (handles ```json fences and chatter)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON in LLM output: {text[:200]}")
    return json.loads(m.group(0))