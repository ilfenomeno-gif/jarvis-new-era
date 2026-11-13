"""Search GitHub repositories with an explicit query."""
from __future__ import annotations

import logging

import requests

from core.connectors import ConnectorError
from core.jarvis_runtime import get_runtime

_LOGGER = logging.getLogger(__name__)
_SEARCH_URL = "https://api.github.com/search/repositories"
_RESULT_LIMIT = 5


def _error_detail(response: requests.Response, token: str) -> str:
    detail = response.text.strip()
    if token:
        detail = detail.replace(token, "[REDACTED]")
    return detail[:500] + ("…" if len(detail) > 500 else "")


def _format_results(query: str, payload: dict) -> str:
    items = payload.get("items")
    total_count = payload.get("total_count")
    if not isinstance(items, list) or not isinstance(total_count, int):
        raise ValueError("GitHub ha restituito risultati di ricerca in formato non valido.")

    repositories = [
        item.get("full_name")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("full_name"), str)
    ]
    if not repositories:
        return f"Non ho trovato repository su GitHub per {query!r}."

    listed = "\n".join(f"- {name}" for name in repositories[:_RESULT_LIMIT])
    return (
        f"Ho trovato {total_count} repository per {query}. "
        f"Ecco i primi {min(len(repositories), _RESULT_LIMIT)} più rilevanti:\n"
        f"{listed}"
    )


def github_search_repositories(parameters: dict) -> str:
    query = str(parameters.get("query", "")).strip()
    if not query:
        return "Specifica una parola o una query da cercare nei repository GitHub."

    connectors = get_runtime().connectors
    ready, reason = connectors.tool_ready("github.search_repositories")
    if not ready:
        return f"C'è stato un errore nella ricerca su GitHub: {reason}"
    token = connectors.access_token("github")
    if not token:
        return (
            "C'è stato un errore nella ricerca su GitHub: "
            "il token non è disponibile; riconnetti GitHub."
        )

    try:
        response = requests.get(
            _SEARCH_URL,
            params={"q": query, "per_page": _RESULT_LIMIT},
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + token,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        return _format_results(query, response.json())
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "sconosciuto"
        detail = _error_detail(response, token) if response is not None else str(exc)
        _LOGGER.warning(
            "GitHub repository search failed with HTTP %s: %s",
            status,
            detail,
        )
        return (
            f"C'è stato un errore nella ricerca su GitHub: HTTP {status}"
            + (f": {detail}" if detail else "")
        )
    except (requests.RequestException, ConnectorError, ValueError) as exc:
        _LOGGER.warning("GitHub repository search failed: %s", exc)
        return f"C'è stato un errore nella ricerca su GitHub: {exc}"
    except Exception as exc:
        _LOGGER.exception("Unexpected GitHub repository search failure")
        return (
            "C'è stato un errore nella ricerca su GitHub: "
            f"{type(exc).__name__}: {exc}"
        )


TOOL = {
    "name": "github_search_repositories",
    "description": (
        "Cerca repository su GitHub per una query esplicita. Usa questo strumento "
        "per richieste come «cerca repository con python», «trova progetti su "
        "GitHub che usano FastAPI» o «cerca repo chiamati jarvis». Imposta query "
        "con i termini effettivamente richiesti dall'utente. Per repository "
        "dell'account autenticato (per esempio «quanti repository ho?»), usa "
        "github_user_repositories. Non usare web_search per cercare repository "
        "GitHub quando la richiesta menziona i repository."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Termini di ricerca GitHub, ad esempio 'python'.",
            }
        },
        "required": ["query"],
    },
    "handler": github_search_repositories,
}
