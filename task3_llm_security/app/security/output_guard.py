"""Guardrail for category 4 (context / system prompt leakage) - the output side.

Whatever the model says is untrusted. Before a reply leaves the server it is compared with the protected
material (canary marker, passcode and every sentence of the system prompt). Matching is done on a
normalized form (lower-case, letters and digits only) so spacing or punctuation tricks do not help.
"""
import re

from .. import settings

REFUSAL = "Sorry, I can't help with that request."


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_SECRETS = [_key(settings.CANARY), _key(settings.PASSCODE)]
_FRAGMENTS = [_key(s) for s in re.split(r"[.\n]", settings.SYSTEM_PROMPT) if len(s.strip()) > 25]


def leaked(reply: str) -> bool:
    k = _key(reply)
    return any(s in k for s in _SECRETS) or any(f in k for f in _FRAGMENTS)


def filter_reply(reply: str) -> tuple[str, bool]:
    """Returns (safe_reply, was_blocked)."""
    return (REFUSAL, True) if leaked(reply) else (reply, False)
