"""Input canonicalisation for category 1 (prompt injection).

This module deliberately contains NO keyword, phrase or regex deny-list. Deciding whether a message is allowed is
done by the semantic guard (semantic_guard.py), where Llama reads the message against the chatbot's rules.

All that happens here is canonicalisation, so that the guard (and the chat model) see the text the way a human
reads it:
  * Unicode NFKC folding, so full-width or otherwise stylised letters become ordinary letters
    ("\uff29\uff47\uff4e\uff4f\uff52\uff45" -> "Ignore");
  * removal of control and zero-width characters that can hide text;
  * whitespace collapsed.
"""
import re
import unicodedata

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL_CHARS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()
