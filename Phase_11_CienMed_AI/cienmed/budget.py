"""Token budget guard — protects your Euri key when the app is shared or deployed.

Every PAID LLM call (a cache miss) is checked here BEFORE it is sent to Euri:
  * cache-only users (guests) may never make a paid call
  * each user has a daily limit of paid calls
  * everyone together has a global daily cap
Cached answers are free and are never counted.

Usage is stored per day in artifacts/usage.json, e.g.
  {"2026-11-12": {"_total": 7, "dr.demo": 4, "admin.demo": 3}}
"""
import contextvars
import json
from datetime import date

from cienmed import config

# Who is asking right now. Set by the orchestrator / report agent for each request.
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar("cienmed_user", default="_system")


class BudgetExceeded(Exception):
    """Raised instead of making a paid call. The message is safe to show to the user."""


def set_user(username: str) -> None:
    _current_user.set(username or "_system")


def current_user() -> str:
    return _current_user.get()


def is_cache_only(username: str | None = None) -> bool:
    return (username or current_user()) in config.CACHE_ONLY_USERS


def _load() -> dict:
    try:
        return json.loads(config.USAGE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def usage_today(username: str | None = None) -> int:
    day = _load().get(date.today().isoformat(), {})
    return day.get(username or current_user(), 0)


def user_limit(username: str | None = None) -> int:
    """Daily paid-call limit for this user: their own `daily_limit` (trial accounts) or the global default."""
    from cienmed import governance
    own = governance.user_daily_limit(username or current_user())
    return own if own is not None else config.USER_DAILY_LIMIT


def total_today() -> int:
    return _load().get(date.today().isoformat(), {}).get("_total", 0)


def check_and_spend() -> None:
    """Call right before a paid LLM request. Raises BudgetExceeded, or records one call."""
    user = current_user()
    if is_cache_only(user):
        raise BudgetExceeded(
            "Live AI is switched off for the demo account. Try one of the example questions — "
            "they are pre-answered. Ask the project owner for a full account to ask your own questions."
        )
    data = _load()
    today = date.today().isoformat()
    day = data.setdefault(today, {})
    if day.get("_total", 0) >= config.GLOBAL_DAILY_LIMIT:
        raise BudgetExceeded("CienMed AI has reached today's overall AI usage limit. Please try again tomorrow.")
    limit = user_limit(user)
    if user != "_system" and day.get(user, 0) >= limit:
        raise BudgetExceeded(
            f"You have reached your daily limit of {limit} AI calls (about "
            f"{limit // 2} new questions). "
            "Previously asked questions still work. Please try again tomorrow."
        )
    day["_total"] = day.get("_total", 0) + 1
    day[user] = day.get(user, 0) + 1
    # keep only the last 30 days
    data = {d: v for d, v in sorted(data.items())[-30:]}
    config.USAGE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")