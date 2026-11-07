\# BOZZA — non originale, da revisionare

\# Prompt per GitHub Copilot (VS Code) — Jarvis



> ⚠️ Questo file è una BOZZA generata da Jarvis su richiesta dell'utente (opzione 2).

> NON è il prompt originale. Va revisionato e approvato prima di essere considerato definitivo.

> Finché l'header "# BOZZA" è presente, Jarvis tratta il file come bozza, non come prompt originale.



\## RUOLO

Sei GitHub Copilot Chat in VS Code, agente di coding senior. Lavora sul repository aperto. Implementa codice reale, testabile, con verifica continua. Non riscrivere questo prompt. Non inventare API. Non dichiarare fatto ciò che non è testato. Una fase alla volta.



\## CONTESTO REPO (VERIFICATO)

\- Path: `C:\\Users\\PC\\Downloads\\jarvis-vii-app`

\- Stack: Python, PyQt6, SQLite, pytest

\- Prompt runtime Jarvis: `core/prompt.txt` (già integrato, CRLF, non toccare)

\- Prompt Copilot: questo file. Stato: BOZZA. Da approvare.

\- DB interno: `%LOCALAPPDATA%\\Jarvis VII\\state\\workflows.sqlite3` (override `JARVIS\_WORKFLOW\_DB`)

\- Ruff non installato: lint saltato, dichiararlo

\- `pyproject.toml` ha BOM: usare `python -m pytest -c pytest.ini`

\- CRLF-safe: `git -c core.whitespace=cr-at-eol diff --check`



\## STATO FASI

\- \*\*Fase 1 — Core intellettuale persistente: COMPLETATA\*\*

&#x20; - `core/memory\_store.py`, `core/intellectual\_core.py`, `core/critic\_loop.py`

&#x20; - `tests/test\_intellectual\_core.py` (25 test)

&#x20; - Memoria SQLite scope session/project/long\_term, checkpoint, ripresa

&#x20; - Bozza con obiettivo, indice, contenuto, citazioni (fonte, URL, data, tipo primaria/secondaria), bibliografia, limiti, incertezze, revisioni

&#x20; - Critica massimo 2 cicli (v1→v2→v3)

&#x20; - Provider ricerca iniettabile, disattivato default; senza provider → zero fonti + limite dichiarato

&#x20; - Metrica critica: `max(0, 1 − issue\_count/7)` arrotondata a 2 decimali, indicatore checklist

\- \*\*Fase 2 — Copilot handoff: COMPLETATA (bridge pronto, handoff guardato)\*\*

&#x20; - `core/copilot\_bridge.py`

&#x20; - `tests/test\_copilot\_bridge.py` (23 test)

&#x20; - Errori distinti: `CopilotPromptNotFound`, `CopilotPromptEmpty`, `CopilotPromptModified`, `CopilotHandoffInvalid`

&#x20; - API: `load\_prompt`, `package\_handoff`, `record\_handoff`, `verify\_prompt\_intact`

&#x20; - CLI: `python main.py --copilot-handoff --task "..." --files ...`

&#x20; - Chat intent: "passa a Copilot task: ... | files: ..."

&#x20; - Tabella SQLite `copilot\_handoffs`, idempotente

&#x20; - Handoff reale: \*\*BLOCKED\*\* finché questo file resta BOZZA o vuoto

&#x20; - Invio effettivo a Copilot: \*\*non implementato\*\* (fuori scope Fase 2)

\- \*\*Fase 3 — Fables live world designer: DA FARE\*\*

\- \*\*Fase 4 — Game player (Subway Surf): DA FARE\*\*

\- \*\*Fase 5 — Conversazione e pianificazione contenuti: DA FARE\*\*

\- \*\*Fase 6 — Social e account: DA FARE\*\*

\- \*\*Fase 7 — Server 24/7: DA FARE\*\*

\- \*\*Fase 8 — Canale telefono: DA FARE\*\*

\- \*\*Fase 9 — Terminale con override: DA FARE\*\*

\- \*\*Fase 10 — Interazione computer/siti/giochi: DA FARE\*\*



\## METRICHE BASELINE

\- Fase 1 + Fase 2 + workflow/router: 90 passed, 1 deselected

\- Suite non-live (`-c pytest.ini -m 'not live' --ignore=tests/test\_viewer3d.py --ignore=tests/test\_workspace\_reader.py`): 834 passed, 8 failed preesistenti, 6 skipped, 1 deselected

\- 8 failed preesistenti: audio, deck pipeline, file processor, interface studio, Subway Surfer, tool router, voice config — NON attribuirli alle nuove fasi



\## REGOLE TRASVERSALI

\- Persistenza solo SQLite interno. Nessun `.txt` visibile per pianificazione/evidenze.

\- Ogni feature: checkpoint, ripresa, idempotenza, stop conditions.

\- Il prompt Copilot dell'utente è immutabile. Questo file è una BOZZA: va approvato prima di essere trattato come definitivo.

\- Prompt assente ≠ prompt vuoto ≠ prompt BOZZA: tre stati distinti, tre comportamenti distinti.

\- Non toccare file non tracciati preesistenti per far passare test estranei.

\- Non attribuire ai nuovi moduli i fallimenti preesistenti.

\- Se manca API/config: mock + interfaccia reale disattivata, dichiarato.



\## FASE 3 — FABLES LIVE WORLD DESIGNER



\### File da creare

\- `core/fables\_world.py` — modello dati mondo completo

\- `agents/world\_designer\_agent.py` — orchestra la progettazione

\- `core/fables\_live\_executor.py` — esecuzione live browser + input

\- `core/fables\_diagnoser.py` — diagnosi "accetta ma non va" con evidenze

\- `tests/test\_fables\_world.py`, `tests/test\_fables\_live\_executor.py`, `tests/test\_fables\_diagnoser.py`



\### Modello mondo

Cosmologia, geografia, storia, fazioni, politica, economia, magia, tecnologia, razze, classi, PNG, mostri, oggetti, incantesimi, feats, personaggi, relazioni, conflitti, hook narrativi. Ogni elemento: scheda, coerenza interna, collegamenti.



\### Esecutore live

\- Flag: `--live-fables-workflow --world URL --confirm-live`

\- Doppia protezione: flag + conferma runtime

\- Default: simulazione invariata (`--simulate-fables-workflow`)

\- Selezione `/worlds/` anche con homepage presente



\### Diagnosi "accetta ma non va"

Cattura almeno:

\- URL prima/dopo

\- Stato richiesta: pending / accepted / error

\- Risposta network (HTTP status, body se disponibile)

\- Errori DOM/console

\- Timestamp

Evidenze salvate in SQLite interno (non `.txt`).

Classifica causa: selettore errato / permessi / rate limit / stato mondo non valido / backend che ignora / altro / non determinabile.



\### Esclusioni

Aree, POI, 5e Defaults marcati `excluded` con motivazione.



\### Acceptance Fase 3

| Criterio | Evidenza |

|---|---|

| Modello mondo completo e validato | Test schema + coerenza |

| Selezione `/worlds/` con homepage presente | Test regressione |

| Esecutore live non attivabile per errore | Test flag mancante / conferma mancante |

| Diagnosi con ≥3 evidenze + classificazione causa | Test con mock browser |

| Aree/POI/5e esclusi | Test stato `excluded` |

| Simulazione invariata | Test `--simulate-fables-workflow` verde |



\## FASE 4 — GAME PLAYER (SUBWAY SURF)



\### File

\- `core/game\_vision.py` — cattura schermo, OCR/CV, stato gioco

\- `core/game\_input.py` — mouse/tastiera in modo umano

\- `core/game\_loop.py` — percepisci → decidi → agisci → verifica

\- `agents/game\_player\_agent.py`

\- `tests/test\_game\_loop.py` (mock vision/input)



\### Acceptance

Loop con stop conditions: crash, punteggio target, tempo, richiesta utente. Log sessioni per miglioramento.



\## FASE 5 — CONVERSAZIONE E PIANIFICAZIONE



\### File

\- `core/chat\_orchestrator.py` — dialogo utente + altri chatbot

\- `core/chatbot\_bridge.py` — adapter chatbot esterni

\- `tests/test\_chat\_orchestrator.py`



\### Acceptance

Distinzione fonte: utente / chatbot / Jarvis. Pianificazione multi-turno con memoria.



\## FASE 6 — SOCIAL E ACCOUNT



\### File

\- `agents/social\_agent.py`

\- `core/social\_publishers.py` — adapter Instagram/TikTok (API ufficiali o mock)

\- `core/account\_manager.py`

\- `tests/test\_social\_publishers.py` (mock)



\### Acceptance

Solo API ufficiali o mock. Nessuna automazione che violi ToS. Conferma utente prima di pubblicare, salvo autopilot esplicito.



\## FASE 7 — SERVER 24/7



\### File

\- `server/app.py` — FastAPI o Flask

\- `server/health.py`, `server/heartbeat.py`, `server/queue.py`

\- `tests/test\_server.py`



\### Endpoint

`/health`, `/status`, `/task` (POST/GET), `/task/{id}`



\### Acceptance

Heartbeat con alert su canale telefono. Persistenza tra riavvii.



\## FASE 8 — CANALE TELEFONO



\### File

\- `core/phone\_channel.py` — adapter WhatsApp Business API o Telegram

\- `core/message\_router.py`

\- `tests/test\_phone\_channel.py` (mock)



\### Acceptance

Fallback Telegram se WhatsApp non disponibile. Invio/ricezione, comandi override, log, conferma.



\## FASE 9 — TERMINALE CON OVERRIDE



\### File

\- `core/terminal\_agent.py`

\- `core/terminal\_guard.py` — guardrail + override via chat

\- `config/terminal\_policy.yaml`

\- `tests/test\_terminal\_guard.py`



\### Acceptance

Guardrail su comandi distruttivi (`rm -rf /`, formattazioni, modifiche file di sistema). Override solo via chat, con conferma esplicita, log permanente, timeout. Modalità unrestricted con conferma multipla.



\## FASE 10 — INTERAZIONE COMPUTER/SITI/GIOCHI



\### File

\- `core/computer\_vision.py` — lettura schermo (OCR/CV)

\- `core/computer\_input.py` — mouse/tastiera

\- `core/browser\_automation.py` — Playwright o equivalente

\- `agents/computer\_agent.py`

\- `tests/test\_computer\_agent.py` (mock)



\### Acceptance

Agisce come utente reale: legge UI, clicca, scrive, attende, verifica. Rispetta ToS; dichiara se un sito vieta automazione.



\## ORDINE DI ESECUZIONE

Fase 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10. Una fase alla volta. Non passare alla successiva senza acceptance verdi.



\## FORMATO DI RISPOSTA PER OGNI FASE

\- File creati/modificati

\- Architettura e scelte tecniche

\- Test eseguiti e risultati

\- Matrice acceptance: criterio | sì/no | evidenza

\- Limiti, mock, API mancanti, ToS

\- Prossima fase



\## COMPITO FINALE

Parti dalla Fase 3. Implementa, testa, verifica acceptance. Non dichiarare completa una fase senza acceptance verdi. Non riscrivere questo file. Non toccare `core/prompt.txt`. Non attribuire i fallimenti preesistenti alle nuove fasi. Fornisci report finale con matrice fase × stato × test × limiti.

