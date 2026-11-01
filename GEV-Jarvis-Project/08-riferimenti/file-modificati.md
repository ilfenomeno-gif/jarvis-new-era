# File modificati dall'integrazione

Elenco ottenuto con `git diff main..feat/gev-integration --name-status` nella repo Jarvis:

| Stato Git | File | Nota |
|---|---|---|
| M | `core/guardrails.py` | Allowlist Node |
| M | `core/plugin_loader.py` | Hook lifecycle |
| A | `docs/GEV_INTEGRATION.md` | Note integrazione/lifecycle |
| M | `main.py` | Eventi e shutdown |
| A | `plugins/gev_plugin.py` | Plugin GEV |
| M | `requirements.txt` | Pin Qt |

Il diff di branch mostra 6 file, 711 aggiunte e 161 rimozioni (`git diff main..feat/gev-integration --stat`).

## Modifiche non committate osservate

- Jarvis: `plugins/gev_plugin.py` modificato nella working tree; contiene schema dispatcher più esteso e tentativo `send_to_gev`. Non fa parte della lista sopra.
- GEV: `.node/` non tracciata, mostrata da `git status --short --branch`; `git check-ignore` non la esclude. Il `.gitignore` letto ha `node_modules` alla riga 1.

> Da verificare: contenuto e provenienza delle risorse non tracciate `.node/`. Nessuna repo sorgente è stata modificata durante la raccolta o il successivo riordino della sola cartella documentale.
