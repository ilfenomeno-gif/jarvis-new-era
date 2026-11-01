# Bridge JARVIS VII ↔ n8n self-hosted (N2)

> Architettura ibrida a due livelli: **JARVIS VII = cervello conversazionale/percettivo**,
> **n8n = orchestratore di workflow/agenti**. Bridge bidirezionale, loopback-only, shared secret in DPAPI.

## Componenti

### 1. JARVIS VII → n8n (delega flussi lunghi)
JARVIS VII chiama un webhook n8n per delegare automazioni multi-step.
- **Azione esistente**: `actions/n8n_bridge.py` (P2). Per il self-hosted, configura `config/n8n.json`:
  ```json
  {
    "base_url": "http://127.0.0.1:5678",
    "webhook_path": "/webhook/jarvis-delegate",
    "auth_header": "X-Jarvis-Token",
    "timeout_sec": 60
  }
  ```
  Nota: il bridge richiede `https://` per default; per il **loopback self-hosted** vedi §"Loopback HTTP" sotto.
- Il segreto del webhook in DPAPI (`n8n:webhook`).

### 2. n8n → JARVIS VII (usa i tool desktop)
JARVIS VII espone i propri tool a n8n su loopback con shared secret.

- **HTTP tool endpoint** (nuovo, `core/tool_server.py`):
  - `GET  http://127.0.0.1:8766/tools` → lista tool + JSON Schema (per discovery).
  - `POST http://127.0.0.1:8766/tool/<name>` con header `X-JARVIS-TOKEN` e body `{"args": {...}}`.
  - Espone solo azioni `read`/`write`; **mai `destructive`** (richiedono il gate di conferma UI).
  - Ogni chiamata in audit log.
- **MCP server** (già presente, `core/mcp_server.py`): espone le azioni come MCP su stdio; n8n 2.x ha `mcpClientTool` per consumarlo. Default read-only.

### Setup del token
Il token condiviso va nel SecretStore DPAPI (mai in chiaro):
```powershell
python -c "from core.secret_store import SecretStore; from pathlib import Path; import getpass; SecretStore(Path('config/secrets.json')).set('n8n:tool_token', getpass.getpass('tool token: '))"
```
In n8n: credenziale **Header Auth** con nome `X-JARVIS-TOKEN` e lo stesso valore.

### Avvio del tool endpoint
```powershell
python -m core.tool_server
```
In ascolto su `http://127.0.0.1:8766` (solo loopback).

## Loopback HTTP
Il bridge `actions/n8n_bridge.py` richiede `https://` per default (regola per webhook pubblici).
Per il **self-hosted su loopback** (`http://127.0.0.1:5678`) la regola va rilassata **solo** per host
loopback: vedi `core/mcp_transport.py` che già applica questa eccezione ("http only on loopback").
Allineare `n8n_bridge._endpoint` alla stessa regola (http consentito solo su 127.0.0.1/localhost).

## Workflow n8n di esempio
`docs/n8n/delegate-workflow.json`: Webhook `jarvis-delegate` → HTTP Request verso
`http://127.0.0.1:8766/tool/<name>` (header `X-JARVIS-TOKEN`) → Respond to Webhook.
