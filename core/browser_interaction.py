"""Safe payload builders for active interaction with the integrated browser."""

from __future__ import annotations

import json
import re


_KEY_ALIASES = {
    "up": "ArrowUp",
    "arrow up": "ArrowUp",
    "arrowup": "ArrowUp",
    "down": "ArrowDown",
    "arrow down": "ArrowDown",
    "arrowdown": "ArrowDown",
    "left": "ArrowLeft",
    "arrow left": "ArrowLeft",
    "arrowleft": "ArrowLeft",
    "right": "ArrowRight",
    "arrow right": "ArrowRight",
    "arrowright": "ArrowRight",
    "space": " ",
    "spacebar": " ",
    " ": " ",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
}

_KEY_DATA = {
    "ArrowUp": ("ArrowUp", 38),
    "ArrowDown": ("ArrowDown", 40),
    "ArrowLeft": ("ArrowLeft", 37),
    "ArrowRight": ("ArrowRight", 39),
    " ": ("Space", 32),
    "Enter": ("Enter", 13),
    "Escape": ("Escape", 27),
}


def normalize_web_key(value: object) -> str:
    """Return a canonical whitelisted key or raise for unsupported input."""
    if not isinstance(value, str):
        raise TypeError("Key must be text")
    raw = value.strip()
    if not raw:
        raise ValueError("Key must not be empty")
    normalized = raw.casefold()
    if normalized in _KEY_ALIASES:
        return _KEY_ALIASES[normalized]
    if len(raw) == 1 and raw.isascii() and raw.isalpha():
        return raw.lower()
    raise ValueError(
        "Unsupported key; allowed keys are A-Z, arrows, Space, Enter and Escape"
    )


def keyboard_event_payload(value: object) -> dict[str, str | int]:
    key = normalize_web_key(value)
    if key in _KEY_DATA:
        code, key_code = _KEY_DATA[key]
        return {"key": key, "code": code, "keyCode": key_code}
    return {"key": key, "code": f"Key{key.upper()}", "keyCode": ord(key.upper())}


def build_keyboard_event_script(value: object) -> str:
    payload = json.dumps(keyboard_event_payload(value), ensure_ascii=True)
    return f"""(() => {{
  const params = {payload};
  const target = document.activeElement || document.body || document.documentElement;
  if (!target) return false;
  for (const type of ["keydown", "keyup"]) {{
    target.dispatchEvent(new KeyboardEvent(type, {{
      key: params.key,
      code: params.code,
      keyCode: params.keyCode,
      which: params.keyCode,
      bubbles: true,
      cancelable: true
    }}));
  }}
  return true;
}})()"""


def normalize_link_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Link text must be text")
    text = " ".join(value.split())
    if not text:
        raise ValueError("Link text must not be empty")
    if len(text) > 500:
        raise ValueError("Link text must not exceed 500 characters")
    return text


def build_click_link_script(value: object) -> str:
    text = normalize_link_text(value)
    payload = json.dumps({"text": text}, ensure_ascii=True)
    return f"""(() => {{
  const params = {payload};
  const requested = params.text.toLocaleLowerCase();
  const links = Array.from(document.links).filter((link) =>
    link.getClientRects().length > 0 &&
    getComputedStyle(link).visibility !== "hidden" &&
    getComputedStyle(link).display !== "none"
  );
  const label = (link) =>
    (link.innerText || link.textContent || "").replace(/\\s+/g, " ").trim().toLocaleLowerCase();
  const exact = links.filter((link) => label(link) === requested);
  const matches = exact.length ? exact : links.filter((link) => label(link).includes(requested));
  if (matches.length !== 1) {{
    return {{ok: false, reason: matches.length ? "ambiguous" : "not-found"}};
  }}
  matches[0].click();
  return {{ok: true}};
}})()"""
