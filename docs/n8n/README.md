# n8n Bridge — configurazione e workflow "echo" di prova

> Il bridge è **configurabile da file**, non cablato su workflow specifici.
> È esposto come **azione** `n8n_bridge` (non anche come plugin: il nome colliderebbe
> con il tool core e verrebbe rifiutato dal plugin loader).
> Canale **solo outbound** (desktop → webhook n8n). Nessuna porta aperta verso internet.
> Il segreto del webhook vive **solo nel SecretStore DPAPI**, mai in chiaro.

## 1. Importare il workflow "echo" in n8n Cloud

1. Apri la tua istanza n8n Cloud → **Workflows** → **⋯ → Import from File**.
2. Seleziona `docs/n8n/echo-workflow.json` (in questa repo).
3. Nel nodo **Webhook**:
   - metodo `POST`, path `jarvis-bridge` (puoi cambiarlo);
   - **Authentication → Header Auth**: crea una credenziale con nome header `X-Jarvis-Token` e un valore segreto lungo e casuale.
   - **Response mode → "Respond to Webhook node"** (risposta sincrona).
4. **Publish** il workflow → copia la **Production URL** (es. `https://<istanza>.app.n8n.cloud/webhook/jarvis-bridge`).

Il workflow risponde con un JSON `{"echo": <task>, "received_at": ...}`: serve solo a
verificare che il canale desktop→n8n funzioni end-to-end.

## 2. Configurare il desktop

Crea `config/n8n.json` (già in `.gitignore`, locale):

```json
{
  "base_url": "https://<istanza>.app.n8n.cloud",
  "webhook_path": "/webhook/jarvis-bridge",
  "auth_header": "X-Jarvis-Token",
  "timeout_sec": 30
}
```

**Regole**: `base_url` deve essere `https://`; il path deve puntare al Webhook node.

## 3. Memorizzare il segreto (DPAPI, mai in chiaro)

Il valore della credenziale n8n va nel SecretStore sotto la chiave `n8n:webhook`.
Non scriverlo in `n8n.json`, nel repo, nei log o in chat. Per impostarlo da Python
(senza stamparlo):

```powershell
python -c "from core.secret_store import SecretStore; from pathlib import Path; import getpass; SecretStore(Path('config/secrets.json')).set('n8n:webhook', getpass.getpass('n8n webhook secret: '))"
```

## 4. Prova

```powershell
python -c "from actions.n8n_bridge import call_workflow; print(call_workflow('ping'))"
```

Atteso: `status=done action=n8n_bridge response={"echo":"ping",...}`.
Con token errato: `status=failed ... authentication`.

## 5. Note di sicurezza

- Payload **solo testo** (`task` + campi extra stringa/numero). Mai audio, screenshot o contenuto schermo.
- Ogni chiamata è registrata in `config/audit.jsonl` (con redaction).
- `risk_class = write`: il bridge può far partire automazioni; non è `destructive` perché la conferma spetta al workflow n8n.
- Per eventi n8n→desktop (P3) si usa un workflow "outbox" in polling: nessuna porta in ingresso.
