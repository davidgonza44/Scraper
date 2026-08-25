"""Safe public image URL helpers for the GUI. Display-only; no fetching."""

from __future__ import annotations

from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "cookie",
        "key",
        "secret",
        "session",
        "sig",
        "signature",
        "token",
    }
)
_MAX_URL_LENGTH = 2048
_MAX_ALT_LENGTH = 160


def safe_public_image_url(value: object) -> str:
    """Return a public http(s) image URL, or blank when the value is unsafe."""

    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw or len(raw) > _MAX_URL_LENGTH:
        return ""
    if any(character.isspace() for character in raw):
        return ""
    folded = raw.casefold()
    if folded.startswith("javascript:") or folded.startswith("data:"):
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return ""
    if not parsed.netloc:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    if "@" in parsed.netloc:
        return ""
    query = parsed.query.casefold()
    if query:
        for part in query.split("&"):
            key = part.split("=", 1)[0]
            if key in _BLOCKED_QUERY_KEYS:
                return ""
    return raw


def image_alt_text(value: object, *, fallback: str = "Imagen del producto") -> str:
    """Compact alt text without control characters."""

    if not isinstance(value, str):
        return fallback
    cleaned = "".join(
        character if character.isprintable() and character != "\t" else " " for character in value
    )
    normalized = " ".join(cleaned.split())
    if not normalized:
        return fallback
    if len(normalized) > _MAX_ALT_LENGTH:
        return normalized[: _MAX_ALT_LENGTH - 1].rstrip() + "…"
    return normalized
