"""List repositories owned by the authenticated GitHub user."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import requests

from core.jarvis_runtime import get_runtime

_API_URL = "https://api.github.com/user/repos"
_REQUIRED_SCOPE = "repo.read"


def _list_repositories(token: str) -> list[dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = _API_URL
    params = {"affiliation": "owner", "per_page": 100}
    repositories: list[dict] = []

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise RuntimeError("GitHub ha restituito un elenco di repository non valido.")
        repositories.extend(
            item
            for item in page
            if isinstance(item, dict)
            and isinstance(item.get("full_name"), str)
        )
        next_url = response.links.get("next", {}).get("url", "")
        if next_url:
            parsed = urlsplit(next_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "api.github.com"
                or parsed.path != "/user/repos"
            ):
                raise RuntimeError("GitHub ha restituito un link di paginazione non valido.")
        url = next_url
        params = None

    return repositories


def github_user_repositories(parameters: dict) -> str:
    """Return repository count/names without requiring model-generated arguments."""
    runtime = get_runtime()
    connectors = runtime.connectors

    if connectors.status("github") != "connected":
        return "GitHub non è connesso. Collega GitHub con un PAT o OAuth e riprova."
    if not connectors.scopes.allows("github", _REQUIRED_SCOPE):
        return (
            "Il permesso repo.read non è stato concesso a Jarvis. "
            "Abilita repo.read nella scheda Plugins & Connections e riprova."
        )
    token = connectors.access_token("github")
    if not token:
        return "Il token GitHub non è disponibile. Ricollega GitHub e riprova."

    try:
        repositories = _list_repositories(token)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "sconosciuto"
        return (
            f"GitHub ha rifiutato la richiesta dei repository (HTTP {status}). "
            "Verifica che il token sia valido e abbia i permessi repo necessari."
        )
    except requests.RequestException as exc:
        return f"Impossibile raggiungere GitHub: {type(exc).__name__}."
    except (ValueError, RuntimeError) as exc:
        return f"Risposta GitHub non valida: {exc}"

    names = [repository["full_name"] for repository in repositories]
    return json.dumps(
        {"count": len(names), "repositories": names},
        ensure_ascii=False,
    )


TOOL = {
    "name": "github_user_repositories",
    "description": (
        "Elenca e conta i repository di proprietà dell'utente GitHub autenticato "
        "in Jarvis. Usa questo strumento quando l'utente chiede dei SUOI repository "
        "(per esempio «quanti repository ho su GitHub?» o «elenca i miei repo»). "
        "Non usare github.search_repositories per queste richieste: quel tool serve "
        "a cercare repository con una query. Questo strumento non richiede argomenti; "
        "se GitHub non è connesso o repo.read manca, spiega come collegarlo o "
        "concedere il permesso. Chiedi un nome utente solo se la richiesta riguarda "
        "un altro account."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": github_user_repositories,
}
