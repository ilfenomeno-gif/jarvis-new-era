"""Headless health response helpers."""


def health_payload() -> dict[str, str]:
    return {"status": "ok"}
