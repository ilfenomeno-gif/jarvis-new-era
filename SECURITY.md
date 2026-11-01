# Checklist di sicurezza — JARVIS VII

## Segreti
- [x] Nessun segreto in chiaro nel repo (scansione pattern api_key/sk-/ghp-/AIza/JWT/AWS/Bearer/github_pat: 0 occorrenze).
- [x] Chiavi solo in **DPAPI SecretStore** (`config/secrets.json`), per-utente Windows.
- [x] `config/api_keys.json`, `config/n8n.json`, `config/certs/`, `*.pem`, `*.key` in `.gitignore`.
- [x] Redaction di token/secret in `audit_log` e `guardrails.redact_sensitive` (estesa: JWT, AWS, Bearer, GitHub PAT).

## Esecuzione comandi
- [x] `guardrails.validate_command`: whitelist eseguibili, shell disabilitata, metacaratteri bloccati, comandi pericolosi rifiutati.
- [x] File policy `regole e vincoli/regole e vincoli.md` **obbligatorio all'avvio**.

## Automazione desktop
- [x] `computer_use`: allowlist processi (default notepad/chrome/msedge/firefox/code) + **emergency stop Ctrl+Alt+Esc**.
- [x] `agent_loop`: passi limitati (default 10, max 50, timeout 30 s/passo).
- [x] `confirm.py`: gate di conferma emesso **dalla UI**, non falsificabile dal modello (timeout 90 s) per azioni `destructive`.
- [x] `undo.py` per operazioni reversibili.

## Plugin
- [x] Discovery con validazione e collision detection; errori non abbattono la scansione.
- [x] **Sandbox opt-in** (`PLUGIN["sandboxed"]=True`): `run()` in sottoprocesso con IPC JSON, timeout, cap output, **nessun import nel processo chiamante**.
- [ ] Limite noto: il sottoprocesso gira come l'utente; confine OS-level (job object/low-rights) **DA VERIFICARE**.

## Rete
- [x] `ws_server`: solo loopback 127.0.0.1:8765, auth HMAC.
- [x] Dashboard: **HTTPS self-signed obbligatorio** + AES-256-GCM (PBKDF2 200k); nessun fallback in chiaro.
- [x] n8n Bridge: **HTTPS obbligatorio**, header auth da DPAPI, timeout, payload **solo testo** (mai audio/schermo), audit.
- [x] n8n→desktop: **solo polling outbound**; nessuna porta aperta verso internet.
- [x] MCP server: default solo `read`; `destructive` mai esposte.

## Prompt injection
- [x] `outcome.untrusted` marca contenuto esterno (web, file, eventi n8n) come dati; escape del marcatore di chiusura.

## Note
- I 3 test `viewer3d` rossi sono preesistenti e non legati alla sicurezza.
- Il bridge n8n non è stato testato contro un'istanza reale (richiede workflow echo + segreto configurati dall'utente).
