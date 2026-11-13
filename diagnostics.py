"""Diagnostica reale e sequenziale delle integrazioni principali di Jarvis.

L'esecuzione normale invia la schermata corrente al provider Vision, apre
Notepad e può rinnovare i token nel vault. --skip-vision evita l'invio.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote

import psutil
import requests

from core.connectors import ConnectorDescriptor, ConnectorError, SecretStoreAuth
from core.env_config import load_env_file
from core.secret_store import SecretStore

ROOT = Path(__file__).resolve().parent
TIMEOUT = 20


class SkipDiagnostic(Exception):
    pass


class DiagnosticFailure(Exception):
    pass


class Diagnostics:
    def __init__(self) -> None:
        load_env_file(ROOT / ".env")
        self.secrets = SecretStore(ROOT / "config" / "secrets.json")
        self.auth = SecretStoreAuth(self.secrets)
        self.http = requests.Session()

    def descriptor(self, connector_id: str) -> ConnectorDescriptor:
        path = ROOT / "connectors" / "catalog" / f"{connector_id}.json"
        return ConnectorDescriptor.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def token(self, descriptor: ConnectorDescriptor) -> str:
        if not self.secrets.get(f"connector:{descriptor.id}"):
            raise SkipDiagnostic("Credenziali mancanti: token non configurato.")
        if descriptor.id != "github":
            client_id, _ = self.auth.oauth_credentials(descriptor)
            if not client_id:
                raise SkipDiagnostic("Credenziali mancanti: Client ID non configurato.")
        try:
            token = self.auth.access_token(descriptor)
        except ConnectorError as exc:
            if descriptor.id == "spotify" and (
                "refresh token non disponibile" in str(exc) or self.invalid_grant(exc)
            ):
                raise SkipDiagnostic(str(exc)) from exc
            raise DiagnosticFailure(self.refresh_error(exc)) from exc
        if not token:
            raise SkipDiagnostic("Credenziali mancanti: token non disponibile.")
        return token

    @staticmethod
    def invalid_grant(exc: ConnectorError) -> bool:
        cause = exc.__cause__
        if not isinstance(cause, HTTPError) or cause.code != 400:
            return False
        try:
            data = json.loads(cause.read(64_000).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, OSError):
            return False
        return isinstance(data, dict) and data.get("error") == "invalid_grant"

    @staticmethod
    def refresh_error(exc: ConnectorError) -> str:
        cause = exc.__cause__
        if isinstance(cause, HTTPError):
            return f"{exc} HTTP {cause.code} {cause.reason}."
        return str(exc)

    def get(self, descriptor: ConnectorDescriptor, url: str, params: dict | None = None) -> dict | list:
        token = self.token(descriptor)
        for attempt in range(2):
            request = requests.Request(
                "GET", url, headers={"Authorization": "Bearer " + token}, params=params
            ).prepare()
            if request.headers.get("Authorization") != "Bearer " + token:
                raise DiagnosticFailure("Header Authorization non valido.")
            response = self.http.send(
                request, timeout=TIMEOUT, allow_redirects=False
            )
            try:
                if response.status_code == 401 and attempt == 0:
                    if not self.secrets.get(f"connector:{descriptor.id}:refresh_token"):
                        if descriptor.id == "spotify":
                            raise SkipDiagnostic("Spotify: HTTP 401 Unauthorized; refresh token mancante.")
                    else:
                        try:
                            refreshed = self.auth.access_token(descriptor, force_refresh=True)
                        except ConnectorError as exc:
                            if descriptor.id == "spotify" and self.invalid_grant(exc):
                                raise SkipDiagnostic(
                                    "Spotify: HTTP 401 Unauthorized; refresh token scaduto o revocato."
                                ) from exc
                            raise DiagnosticFailure(
                                f"HTTP 401 Unauthorized; rinnovo token fallito: {self.refresh_error(exc)}"
                            ) from exc
                        if not refreshed:
                            raise DiagnosticFailure("HTTP 401 Unauthorized; rinnovo token non disponibile.")
                        token = refreshed
                        continue
                if response.status_code < 200 or response.status_code >= 300:
                    detail = f"HTTP {response.status_code} {response.reason}"
                    try:
                        error_data = response.json()
                    except requests.exceptions.JSONDecodeError:
                        error_data = None
                    if isinstance(error_data, dict):
                        provider_error = error_data.get("error")
                        if isinstance(provider_error, dict):
                            provider_error = provider_error.get("message")
                        if isinstance(provider_error, str) and provider_error:
                            detail += ": " + provider_error.replace(token, "[REDACTED]")
                    if descriptor.id == "google-workspace" and response.status_code == 403:
                        detail += (
                            "; accesso negato: verifica lo scope richiesto e che l'API "
                            "sia abilitata nel progetto Google Cloud."
                        )
                    if descriptor.id == "spotify" and response.status_code == 401:
                        raise SkipDiagnostic(detail + "; token scaduto o non valido.")
                    raise DiagnosticFailure(detail)
                try:
                    data = response.json()
                except requests.exceptions.JSONDecodeError as exc:
                    raise DiagnosticFailure(f"Risposta JSON non valida: {exc}") from exc
                if not isinstance(data, (dict, list)):
                    raise DiagnosticFailure("Risposta JSON inattesa.")
                return data
            finally:
                response.close()
        raise DiagnosticFailure("Richiesta non riuscita dopo il rinnovo del token.")

    def gmail(self) -> str:
        descriptor = self.descriptor("google-workspace")
        base = "https://gmail.googleapis.com/gmail/v1/users/me"
        try:
            profile = self.get(descriptor, base + "/profile")
            if not isinstance(profile, dict) or not isinstance(profile.get("emailAddress"), str):
                raise DiagnosticFailure("Profilo Gmail privo di emailAddress.")
            result = self.get(descriptor, base + "/messages", {"maxResults": 1})
            if not isinstance(result, dict):
                raise DiagnosticFailure("Elenco Gmail non valido.")
            messages = result.get("messages", [])
            if not isinstance(messages, list):
                raise DiagnosticFailure("Elenco messaggi Gmail non valido.")
            if not messages:
                return "Profilo accessibile; nessuna email trovata."
            message = messages[0]
            if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not message["id"]:
                raise DiagnosticFailure("ID messaggio Gmail mancante.")
            detail = self.get(
                descriptor, base + "/messages/" + quote(message["id"], safe=""),
                {"format": "metadata", "metadataHeaders": "Subject"},
            )
            payload = detail.get("payload") if isinstance(detail, dict) else None
            headers = payload.get("headers") if isinstance(payload, dict) else None
            if not isinstance(headers, list):
                raise DiagnosticFailure("Intestazioni Gmail non disponibili.")
            subject = next(
                (header["value"] for header in headers
                 if isinstance(header, dict)
                 and str(header.get("name", "")).lower() == "subject"
                 and isinstance(header.get("value"), str)),
                None,
            )
            return (
                "Profilo e ultima email accessibili; oggetto recuperato (non mostrato)."
                if subject is not None else
                "Profilo e ultima email accessibili; intestazione Subject assente."
            )
        except DiagnosticFailure as exc:
            if "HTTP 403" in str(exc):
                raise DiagnosticFailure(
                    f"{exc} Possibile scope gmail.readonly mancante."
                ) from exc
            raise

    def calendar(self) -> str:
        result = self.get(
            self.descriptor("google-workspace"),
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            {"maxResults": 1},
        )
        if not isinstance(result, dict) or not isinstance(result.get("items", []), list):
            raise DiagnosticFailure("Elenco eventi Calendar non valido.")
        return "Calendario primario accessibile."

    def github(self) -> str:
        result = self.get(
            self.descriptor("github"), "https://api.github.com/user/repos", {"per_page": 1}
        )
        if not isinstance(result, list):
            raise DiagnosticFailure("Elenco repository GitHub non valido.")
        return "Authorization Bearer inviato; endpoint repository accessibile."

    def spotify(self) -> str:
        result = self.get(self.descriptor("spotify"), "https://api.spotify.com/v1/me")
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            raise DiagnosticFailure("Profilo Spotify non valido.")
        return "Profilo Spotify accessibile."

    @staticmethod
    def vision() -> str:
        from actions import capture_and_analyze_screen as vision
        from actions.screen_processor import _get_api_key

        try:
            api_key = _get_api_key()
        except RuntimeError as exc:
            if "mancante" in str(exc).lower():
                raise SkipDiagnostic(f"Credenziali mancanti: {exc}") from exc
            raise
        completed = subprocess.run(
            [sys.executable, str(ROOT / "diagnostics.py"), "--vision-worker"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=vision.VISION_PROCESS_TIMEOUT_SECONDS + 30, check=False,
        )
        output = completed.stdout + "\n" + completed.stderr
        marker = "DIAGNOSTIC_VISION_RESULT="
        result_lines = [line for line in completed.stdout.splitlines() if line.startswith(marker)]
        if completed.returncode != 0 or not result_lines:
            errors = [
                line.replace(api_key, "[REDACTED]")
                for line in output.splitlines()
                if re.search(r"errore|error|exception|traceback", line, re.I)
                and not line.startswith(marker)
            ]
            raise DiagnosticFailure(
                f"Processo Vision terminato con codice {completed.returncode}; "
                + (errors[-1][:500] if errors else "nessun risultato diagnostico.")
            )
        result = json.loads(result_lines[-1][len(marker):])
        failures = {
            vision.VISION_EMPTY_MESSAGE, vision.VISION_QUOTA_MESSAGE,
            vision.VISION_OVERLOAD_MESSAGE, vision.VISION_INTERNAL_MESSAGE,
            vision.VISION_COOLDOWN_MESSAGE, vision.VISION_SLOW_MESSAGE,
        }
        if not isinstance(result, str) or not result.strip():
            raise DiagnosticFailure("Vision non ha restituito testo descrittivo.")
        if result in failures:
            raise DiagnosticFailure(result)
        for line in output.splitlines():
            if (
                re.search(r"\b(?:429|500|RESOURCE_EXHAUSTED|INTERNAL)\b", line, re.I)
                and re.search(r"errore|error|failed|quota|esaurit", line, re.I)
            ):
                raise DiagnosticFailure(
                    "Vision ha incontrato un errore 429/500 durante la richiesta: "
                    + line[:500]
                )
        return "Vision ha restituito testo descrittivo (non mostrato)."

    @staticmethod
    def terminal() -> str:
        from actions.terminal import terminal_run

        result = terminal_run({"command": "echo test_api_ok", "confirmed": True})
        if result.get("returncode") != 0:
            raise DiagnosticFailure(str(result.get("stderr") or result))
        if "test_api_ok" not in result.get("stdout", ""):
            raise DiagnosticFailure("Output del terminale non contiene test_api_ok.")
        return "Output test_api_ok verificato."

    @staticmethod
    def launcher() -> str:
        if os.name != "nt":
            raise SkipDiagnostic("App Launcher è disponibile solo su Windows.")
        from actions.app_launcher import app_launcher

        started = time.time()
        outcome = app_launcher({"name": "notepad.exe", "confirmed": True})
        launched = outcome.startswith(("Launch requested", "Launch started", "Launch completed"))
        if not launched and not outcome.startswith("Ho aperto "):
            raise DiagnosticFailure(outcome)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for process in psutil.process_iter(["name", "create_time"]):
                try:
                    if (
                        (process.info["name"] or "").casefold() == "notepad.exe"
                        and process.info["create_time"] >= started
                        and psutil.pid_exists(process.pid)
                    ):
                        return f"Notepad avviato; PID {process.pid} verificato."
                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
                    continue
            time.sleep(0.1)
        raise DiagnosticFailure(
            outcome + " Nessun nuovo processo notepad.exe verificabile tramite PID."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-vision", action="store_true",
        help="Non acquisire né inviare la schermata a Gemini.",
    )
    parser.add_argument("--vision-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.vision_worker:
        from actions.capture_and_analyze_screen import capture_and_analyze_screen

        result = capture_and_analyze_screen({"question": "Descrivi brevemente la schermata."})
        print("DIAGNOSTIC_VISION_RESULT=" + json.dumps(result, ensure_ascii=True), flush=True)
        return 0
    diagnostics = Diagnostics()
    checks = (
        ("Google Gmail", diagnostics.gmail),
        ("Google Calendar", diagnostics.calendar),
        ("GitHub", diagnostics.github),
        ("Spotify", diagnostics.spotify),
        ("Vision", diagnostics.vision),
        ("Terminale", diagnostics.terminal),
        ("App Launcher", diagnostics.launcher),
    )
    has_failure = False
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as results:
        try:
            for name, check in checks:
                start = time.perf_counter()
                try:
                    if name == "Vision" and args.skip_vision:
                        raise SkipDiagnostic("Acquisizione e invio schermata disabilitati.")
                    detail = check()
                    status = "OK"
                except SkipDiagnostic as exc:
                    status, detail = "SKIP", str(exc)
                except Exception as exc:
                    status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
                    has_failure = True
                elapsed = (time.perf_counter() - start) * 1000
                detail = re.sub(r"[\r\n]+", " ", detail)
                results.write(json.dumps([name, status, elapsed, detail], ensure_ascii=True) + "\n")
                print(f"[{status}] {name} - {elapsed:.1f} ms - {detail}", flush=True)
        finally:
            diagnostics.http.close()

        print("\nRiepilogo:")
        print(f"{'API':<18} {'Stato':<7} {'Latenza':>12}  Errore / dettaglio")
        print("-" * 100)
        results.seek(0)
        for line in results:
            name, status, elapsed, detail = json.loads(line)
            print(f"{name:<18} {status:<7} {elapsed:>9.1f} ms  {detail}")
    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
