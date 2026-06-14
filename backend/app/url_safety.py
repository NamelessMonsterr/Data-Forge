"""URL validation helpers for externally supplied dataset links."""

from __future__ import annotations

import re
import urllib.parse


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def is_safe_http_url(value: object, *, allow_empty: bool = False) -> bool:
    """Return True only for absolute http(s) URLs with a host."""
    try:
        validate_http_url(value, allow_empty=allow_empty)
        return True
    except ValueError:
        return False


def validate_http_url(value: object, *, allow_empty: bool = False) -> str:
    """Normalize and validate an externally supplied link.

    Only absolute ``http://`` and ``https://`` URLs with a network location are
    accepted. Scheme-relative, javascript/data/file/mailto, and control-character
    obfuscated URLs are rejected before they can be persisted or rendered.
    """
    url = str(value or "").strip()
    if not url:
        if allow_empty:
            return ""
        raise ValueError("URL is required.")
    if _CONTROL_CHARS.search(url):
        raise ValueError("URL contains invalid characters.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("URL must use http or https.")
    if not parsed.netloc:
        raise ValueError("URL must include a host.")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include credentials.")
    return urllib.parse.urlunparse(parsed._replace(scheme=parsed.scheme.lower()))
