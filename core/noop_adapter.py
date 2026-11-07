class NoopAdapter:
    name = "none"

    def health(self) -> dict:
        return {"provider": self.name, "ok": False, "error_code": "not_configured"}
