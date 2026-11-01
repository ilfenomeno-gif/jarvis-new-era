"""URL validation and normalization for the embedded browser."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_SITE_ALIASES = {
    "youtube": "https://www.youtube.com/",
}


def is_allowed_http_scheme(scheme: str) -> bool:
    return scheme.casefold() in {"http", "https"}


def normalize_http_url(value: str) -> str:
    """Return a normalized HTTP(S) URL, rejecting non-web schemes."""
    if not isinstance(value, str):
        raise TypeError("URL must be text")

    candidate = value.strip()
    if not candidate:
        raise ValueError("URL cannot be empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise ValueError("URL cannot contain control characters")

    alias = _SITE_ALIASES.get(candidate.casefold())
    if alias is not None:
        return alias

    scheme_match = _SCHEME_RE.match(candidate)
    if scheme_match:
        entered_scheme = scheme_match.group(1).casefold()
        if entered_scheme in {"http", "https"}:
            pass
        elif "://" in candidate:
            raise ValueError("Only http and https URLs are allowed")
        else:
            host, separator, port = candidate.partition(":")
            port = re.split(r"[/#?]", port, maxsplit=1)[0]
            looks_like_host_port = (
                bool(separator)
                and port.isdigit()
                and ("." in host or host.casefold() == "localhost")
            )
            if not looks_like_host_port:
                raise ValueError("Only http and https URLs are allowed")
            candidate = f"https://{candidate}"
    elif candidate.startswith("//"):
        candidate = f"https:{candidate}"
    else:
        candidate = f"https://{candidate}"

    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid web URL: {exc}") from exc

    scheme = parsed.scheme.casefold()
    if not is_allowed_http_scheme(scheme):
        raise ValueError("Only http and https URLs are allowed")
    if not hostname or any(char.isspace() for char in hostname):
        raise ValueError("URL must include a valid host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials are not allowed in browser URLs")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL port must be between 1 and 65535")

    return urlunsplit(
        (scheme, parsed.netloc, parsed.path or "/", parsed.query, parsed.fragment)
    )
