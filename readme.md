# JARVIS VII

Assistente desktop AI personale (Windows-first), fusione di:

- **B** — [`ilfenomeno-gif/jarvis-new-gen`](https://github.com/ilfenomeno-gif/jarvis-new-gen) (`Mark-LIV-main`, baseline `origin/main` @ `41e405e`): app desktop PyQt6 + Gemini Live, sicurezza (guardrail, DPAPI, audit, conferme UI), plugin, multi-agente, GEV, 3D, ~55 file di test.
- **C** — [`FatihMakes/Mark-LVI`](https://github.com/FatihMakes/Mark-LVI) (@ `4d4035c`): layer `providers/` (motore STT+LLM+TTS intercambiabile con fallback a Gemini Live), protocollo `outcome` (done/unverified/failed), dashboard HTTPS+AES-GCM, avatar olografico.
- **A** — n8n Cloud come **motore di workflow** via webhook (canale solo outbound; eventi n8n→desktop via polling "outbox").

**Architettura**: Opzione 2 — *Python come cervello, n8n come motore di workflow*. Il realtime vocale resta sul desktop; n8n orchestra flussi/integrazioni/schedulazioni come tool remoto.

## Cosa c'è di nuovo rispetto a B

| Area | Aggiunta | File |
|---|---|---|
| Motore intercambiabile | `providers/` (Ollama, Whisper, Piper, OpenAI-compat…) con fallback automatico a Gemini Live | `providers/`, `main.py` (`_engine_mode`/`_resolve_engine_caps`/`_open_session`) |
| Esiti onesti | protocollo `done/unverified/failed/ask/started` + wrapper anti prompt-injection | `core/outcome.py` |
| Config provider | modalità `gemini`/`pipeline`, pipeline STT/LLM/TTS, sidecar, plugin_config | `memory/config_manager.py` |
| Dashboard indurita | HTTPS self-signed obbligatorio + AES-256-GCM (PBKDF2 200k) | `dashboard/server.py` |
| n8n Bridge | azione `n8n_bridge` (HTTPS, header auth, timeout, outcome, audit, payload solo testo) | `actions/n8n_bridge.py`, `docs/n8n/` |
| n8n → desktop | polling "outbox" (nessuna porta aperta), notifica HUD/log | `core/n8n_outbox.py` |
| Sandbox plugin | sottoprocesso + IPC JSON dichiarativa, opt-in `PLUGIN["sandboxed"]` | `core/plugin_sandbox.py`, `core/_plugin_sandbox_worker.py` |
| Redaction estesa | JWT, AWS, Bearer, GitHub PAT | `core/guardrails.py` |
| UI Iris + HUD | Splash animata iniziale a 705 nodi, poi mappa 3D; Iris si mostra su richiesta, chat, metriche, tab SISTEMA, tour e comandi restano nell'overlay | `core/jarvis_hud.html`, `actions/hud_control.py` |
| Avatar desktop nativo | opt-in via `hud_style="face"` (default `core` invariato), indipendente dall'iframe Iris | `ui.py`, `core/avatar.py` |

La HUD HTML viene mostrata già durante l'avvio di Qt, invece della vecchia HUD
nativa transitoria; si collega al bridge locale appena è disponibile. Mostra una
sequenza iniziale animata a 705 nodi, collegata allo stato reale del runtime e con
chiusura di sicurezza se il bridge non risponde; poi presenta la mappa 3D.
L'avatar è presentato come
**Iris** nell'interfaccia, ma viene ancora fornito dal sito esterno
`https://mira-humanoid.vercel.app/`; viene caricato solo quando si pronuncia o si invia
il comando esatto **“Iris rivelati”**; **“Iris nasconditi”** lo richiude.
Quando viene rivelata, Iris sostituisce la mappa a schermo intero e lascia visibile
solo la chat flottante. Il rendering Three.js della mappa viene sospeso mentre Iris
è aperta; sulla mappa la scena è limitata a 30 FPS e pixel ratio 1,5 per contenere
il carico GPU.
L'iframe è cross-origin: la HUD non può rinominare o sincronizzare liberamente il
sito. Nel frame HTTPS dell'origine Mira, JARVIS abilita la riproduzione senza gesto
e preme automaticamente solo il pulsante iniziale `ENTER`, se presente; così Iris
entra direttamente senza automatizzare camera o microfono. La navigazione resta
limitata all'origine Mira. Quando Iris viene mostrata, la voce Live passa a Kore;
quando si torna alla mappa, JARVIS riprende la voce maschile configurata (o Charon
se la voce salvata è femminile). Il cambio ricrea la sessione Live per applicare
la voce.
L'host Qt consente la pagina principale solo sul
bridge locale e il frame HTTPS solo per l'origine Mira; nasconde il chrome Qt duplicato
quando la HUD web è attiva.

## Contratti provider e tracing vocale

La pipeline locale accetta STT, LLM e TTS iniettati secondo i protocolli di
`providers/base.py`. La suite isolata usa provider mock e verifica i payload,
lo schema tool, timeout, retry limitati e recovery da JSON di tool call
malformato, senza avviare Qt o il runtime vocale:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_provider_contracts.py
```

I retry sono limitati a errori di trasporto, fino a tre tentativi configurabili;
una risposta LLM o audio TTS già emessa non viene mai ripetuta. I limiti
predefiniti sono un retry e 60 secondi per tentativo/stallo dello stream. La pipeline emette span
OpenTelemetry `voice.turn`, `voice.stt`, `voice.llm` e `voice.tts`; le esecuzioni
di tool vocali emettono `voice.tool`. I transcript non vengono registrati come
attributi, per non esportare contenuto privato. L'app include l'API
OpenTelemetry; per raccogliere o esportare span va configurato uno
`TracerProvider`/exporter nell'host. Gli screenshot 3D validati sono salvati in
`Pictures\JARVIS\3D`.

## Avvio, logging e test di performance

`JARVIS_LOG_LEVEL` configura il livello del logger Python (default `INFO`, ad
esempio `DEBUG`). `JARVIS_UI_LAYOUT` seleziona il file di layout HUD/UI;
`JARVIS_HUD_PORT` cambia la porta locale del bridge (default `8765`, `0` assegna
una porta effimera). L'opzione CLI `--hud-port` prevale sulla variabile
d'ambiente, ad esempio `python main.py --hud-port 8766`. I test usano profili
temporanei e non toccano il layout salvato dell'utente.
Il livello `DEBUG` non registra payload sensibili; se nei log compaiono
credenziali, è un bug: apri una issue.

La suite automatica non-live imposta Qt offscreen tramite `tests/conftest.py`;
i test che creano finestre QtWebEngine reali vengono saltati in questa modalita
per evitare crash nativi. Non serve impostare `CI=true`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs -m "not live" --ignore=tests\test_viewer3d.py
```

Ultima esecuzione locale: **1157 passed, 10 skipped, 5 deselected, 4 xfailed**.
I test UI QtWebEngine con finestra reale sono al momento **solo locali/manuali**:
eseguili da una sessione Windows interattiva con display disponibile, senza
`CI=true` e impostando `QT_QPA_PLATFORM=windows`, ad esempio:

```powershell
$env:QT_QPA_PLATFORM = "windows"
.\.venv\Scripts\python.exe -m pytest -q tests\test_ui_panels.py tests\test_viewer3d.py
```

Non sono eseguiti dal workflow offscreen; non e' configurato un runner desktop
interattivo dedicato.

Il test di cold start è opt-in e controlla che UI e HUD rispondano senza chiavi
provider; salta se la porta HUD scelta è già occupata:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -m live tests\test_startup.py
```

I report CLI dei benchmark usano [schema JSON v1](benchmarks/benchmark-report.schema.json).
Il confronto mediano usa solo report con nome, configurazione e insieme metriche
compatibili; supera `--max-regression-percent` per cambiare la soglia (default
10%):

```powershell
.\.venv\Scripts\python.exe benchmarks\bench_core.py --iterations 1000 --runs 3 --output test-evidence\core.json
.\.venv\Scripts\python.exe scripts\compare_bench.py test-evidence\baseline.json test-evidence\core.json --max-regression-percent 10
.\.venv\Scripts\python.exe benchmarks\bench_ttft_live.py --repeats 20 --timeout-seconds 1800 --output test-evidence\ttft.json
```

Il benchmark TTFT interroga Ollama locale ed è eseguito solo manualmente; non fa
parte dei test rapidi e non è schedulato in CI. Il job live GitHub è disponibile
solo con `workflow_dispatch`, dato che la latenza dipende dall'hardware del
runner. `bench_core.py` è offline e accetta `--iterations` da 200 a 100000 e
`--runs` da 3 a 5.
Nei report TTFT, `stream.*` significa tempo al primo contenuto emesso dal motore;
`buffered.*` significa tempo al completamento della risposta, non TTFT. Il campo
`metric_semantics` rende esplicita questa distinzione anche nei JSON archiviati.
La baseline presente usa 20 ripetizioni per prompt/modalità: le mediane sono
indicative e i percentili di coda non sono ancora stabili; raccogli almeno 50
campioni per prompt/modalità prima di usare p95/p99 come baseline comparativa.

## Workflow interno Fables

I workflow Jarvis sono persistiti in SQLite nell'area dati privata dell'utente
(`%LOCALAPPDATA%\Jarvis VII\state\workflows.sqlite3` su Windows), non in file di
appunti visibili nella cartella del progetto. `JARVIS_WORKFLOW_DB` consente di
selezionare un archivio alternativo per test. Il coordinatore salva piano,
checklist, eventi idempotenti e checkpoint; non attiva azioni del browser in fase
di pianificazione o simulazione.

Il flusso Fables registra 12 voci: profilo/altre modalità uniche, 5e Defaults,
razze, classi, feats, mostri, oggetti, incantesimi, personaggi, fazioni, Aree e
POI. Le modalità uniche restano solo in valutazione; 5e Defaults, Aree e POI sono
bloccati come operazioni del workflow (non attivare i defaults, non creare Aree/POI);
lo stato attuale del mondo non viene cambiato né verificato. Gli agenti esistenti sono assegnati per ruolo (coordinamento, fonti e
diagnosi), ma la simulazione non chiama le loro API né Gemini.

Per riprodurre il caso richiesto senza rete, browser, API o modifiche al mondo:

```powershell
.\.venv\Scripts\python.exe main.py --simulate-fables-workflow
```

Il comando restituisce esito `blocked` quando la transizione post-accettazione
non è verificata; questo è l'esito atteso del caso sintetico, non una diagnosi
del guasto reale di Friends & Fables.

Il preflight live, separato dalla simulazione, richiede sia `--confirm-live` sia
una frase digitata esattamente a runtime:

```powershell
python main.py --live-fables-workflow --world "https://play.fables.gg/worlds/01a18d96-5091-7c68-9144-2039b73fe2d3" --confirm-live
```

Questa versione del preflight naviga e legge il testo visibile, quindi registra
URL, hash del testo e limiti di osservazione nel database privato. Non accetta
richieste, non invoca agenti e non crea contenuti: gli strumenti browser attuali
non forniscono evidenze network/console né un flusso Fables specifico verificato.
Il comando si arresta `blocked` se lo stato della richiesta non è verificabile.
`JARVIS_WORKFLOW_MAX_CYCLES` limita il loop di workflow (1–50, default 24);
`JARVIS_LOCAL_TOOL_CYCLES` controlla i cicli del brain locale (1–50, default 12).

### Fables World Designer e diagnosi live (Fase 3)

`core/fables_world.py` modella i 19 ambiti del mondo con schede, note di
coerenza e collegamenti tra record. Aree, punti di interesse e 5e Defaults sono
sempre salvati come `excluded` con motivazione. `agents/world_designer_agent.py`
valida il modello, può invocare planner/research/critic iniettati, salva un
checkpoint SQLite e permette di riprendere la bozza tramite il suo ID.

L'esecuzione dal sito non presume selettori Fables: richiede un mapping UI
verificato in JSON con le etichette `create_label`, `name_label`, `card_label`
e `submit_label` per ogni categoria da creare. Le diagnosi persistono URL,
stato richiesta, risposte network, errori DOM/console e timestamp in SQLite;
le risposte HTTP omettono query string e corpi per evitare di salvare token o
contenuti sensibili. Lo stato resta `pending` quando la risposta non prova sia
un HTTP 2xx sia la comparsa visibile dell'elemento.

Per eseguire una bozza già salvata, servono i due flag live, un ID bozza,
`config/fables_forms.json` con mapping controllati e una frase runtime esatta:

```powershell
python main.py --live-fables-workflow --world "https://play.fables.gg/worlds/..." --confirm-live --world-draft-id "<id>"
```

La conferma richiesta è `AUTORIZZO ESECUZIONE FABLES <URL>`. Il comando
`--live-fables-workflow` senza `--world-draft-id` rimane il preflight
osservativo. Nessuna interazione live è stata eseguita durante i test; i test
dell'esecutore usano adapter mock. L'interfaccia attuale non fornisce un mapping
di form Fables verificato: la scrittura resta bloccata finché l'utente non lo
configura e conferma.

Per diagnosticare una richiesta di partecipazione che dovrebbe aprire un mondo,
il comando seguente apre la pagina indicata e attiva una sola volta l'etichetta
UI verificata. Registra prima/dopo, stato HTTP, errori e diagnosi SQLite; non
ripete una richiesta già checkpointata:

```powershell
python main.py --live-fables-workflow --confirm-live --diagnose-accepted-request --request-page "https://fables.gg/requests/<id>" --request-id "<id>" --accept-label "Accept request" --world "https://play.fables.gg/worlds/<world-id>"
```

La conferma runtime richiesta è
`AUTORIZZO DIAGNOSI RICHIESTA FABLES <pagina> -> <mondo> [<id>]`.
Questo comando esegue un click reale: non usarlo se l'azione è già stata
accettata prima dell'avvio; il checkpoint evita solo esecuzioni successive
dello stesso ID richiesta.

### Game Player Subway Surfers (Fase 4)

`core/game_vision.py` espone `GameVision.perceive()` e il modello `GameState`.
Il provider desktop predefinito cattura uno screenshot e usa OCR se sono
disponibili PyAutoGUI, Pillow e pytesseract; per CV/ML o test, inietta
`frame_provider` e `frame_analyzer`. `core/game_input.py` offre swipe, salto e
roll con ritardo casuale limitato e dispatcher iniettabile.

`core/game_loop.py` applica percepisci/decidi/agisci/verifica e arresta la
sessione su crash, target score, timeout, stop utente o limite di passi.
Il riepilogo è salvato nella tabella SQLite `game_sessions`. `GamePlayerAgent`
fornisce l'avvio in background e lo stop tramite evento. I test usano frame,
input e clock mock; non simulano né autorizzano input desktop reale. L'OCR
predefinito legge fatti HUD testuali: per riconoscere ostacoli da immagini va
fornito un analyzer CV dedicato.

### Chat Orchestrator (Fase 5)

`core/chatbot_bridge.py` definisce `BaseChatbot` e `MockChatbot`; gli adapter
esterni possono implementare lo stesso `send_message()` senza modificare il
coordinatore. `core/chat_orchestrator.py` mantiene conversazioni multi-turno
attribuendo ogni messaggio a `user`, `chatbot` (con nome) o `jarvis`, e salva
sessione, checkpoint, eventi e punti chiave in `MemoryStore`/SQLite.
`plan_content(topic, user_preferences)` inoltra ai chatbot configurati un
contesto JSON che distingue le fonti e restituisce un piano strutturato con
suggerimenti attribuiti, sintesi di Jarvis e scaletta. Senza adapter esterni,
dichiara esplicitamente che il piano usa solo il contesto locale. In questa
fase non vengono chiamate API esterne dai test o dal bridge mock.

### Social Agent (Fase 6)

`core/account_manager.py` salva i token solo nel `SecretStore` cifrato (DPAPI
su Windows) e conserva in SQLite soltanto piattaforma e username; in alternativa
può leggere `SOCIAL_INSTAGRAM_USERNAME` / `SOCIAL_INSTAGRAM_TOKEN` o le
corrispondenti `SOCIAL_TIKTOK_*`. Se il backend sicuro non è disponibile, il
salvataggio del token fallisce esplicitamente, senza fallback in chiaro.

`core/social_publishers.py` definisce `BasePublisher`, un mock e adapter
Instagram/TikTok che richiedono un client fornito dall'integrazione con le API
ufficiali. Non sono implementati scraping, automazione browser o bot non
autorizzati. `agents/social_agent.py` prepara bozze e pubblica solo dopo una
conferma che restituisca esplicitamente `True`; l'autopilot è disattivato per
default e va abilitato tramite configurazione esplicita del costruttore.
Bozze e stato delle pubblicazioni sono registrati in SQLite. Ogni bozza può
essere inviata una sola volta; errori e log non includono token o messaggi grezzi
restituiti dai publisher.

### Server headless e task queue (Fase 7)

Avvio locale: `python -m server.app` (FastAPI/Uvicorn su `127.0.0.1:8765`).
Il server non importa né avvia la GUI PyQt. Gli endpoint sono `GET /health`,
`GET /status`, `POST /task` con `{"task":"..."}` e `GET /task/{task_id}`.
Task e heartbeat sono persistiti nel database SQLite interno. Un task lasciato
`running` da un arresto viene rimesso `pending` al riavvio (consegna at-least-once;
gli handler che fanno effetti esterni devono essere idempotenti). Il worker
predefinito consuma e conferma la ricezione, ma non esegue azioni dell'agente
Jarvis; passare `task_handler` a `create_app()` per collegare un executor.

Non esporre questa API direttamente a reti non fidate: l'avvio predefinito è
solo loopback e non implementa autenticazione. Il servizio non configura
l'avvio automatico del sistema operativo; per funzionare 24/7 va registrato
come servizio/task scheduler dall'amministratore. L'heartbeat persiste timestamp
e offre `alert_callback` iniettabile per una futura integrazione notifiche.

### Phone Channel (Fase 8)

`core/phone_channel.py` definisce `BasePhoneChannel`, un mock in memoria e un
`TelegramAdapter` basato sul Bot API HTTPS. L'adapter Telegram resta disabilitato
finché `enabled=True` non viene passato esplicitamente; il token va inserito nel
`SecretStore` sotto la chiave `phone:telegram:bot_token`. Chat ID e token non
sono inclusi in repr, log o messaggi di errore. `core/message_router.py` instrada
messaggi normali a Jarvis, `/status` e `/stop` ai rispettivi handler, e
`AUTORIZZO OVERRIDE` all'hook di sicurezza: l'override non viene autorizzato
automaticamente. L'inbound è fail-closed: senza `allowed_sender_ids` nessun
mittente viene elaborato. L'invio richiede un canale configurato; i test usano
solo mock e trasporti finti. Non vengono inviati messaggi reali.

### Terminal Agent (Fase 9)

`core/terminal_guard.py` carica `config/terminal_policy.yaml` e consente solo
gli eseguibili esplicitamente elencati; comandi non riconosciuti richiedono un
override, mentre input malformati e operatori di shell vengono rifiutati senza
possibilità di override. `core/terminal_agent.py` avvia i processi con
`shell=False`, timeout e output acquisito. L'override richiede il token esplicito
`AUTORIZZO OVERRIDE`, vale per la singola esecuzione e registra esito, motivo,
comando e ID mittente (se disponibile) in SQLite. Il router telefonico inoltra
solo i messaggi di mittenti autorizzati al gestore override configurato.
La policy e il timeout sono protezioni aggiuntive, non sostituiscono il normale
controllo dell'utente sui comandi eseguiti.

### Computer Agent (Fase 10)

`core/computer_vision.py` cattura lo schermo solo quando viene chiamato e usa
OCR locale iniettabile per trovare testo e coordinate. `core/computer_input.py`
invia azioni desktop con pause casuali; i test usano dispatcher e clock mock.
`core/browser_automation.py` avvia Playwright soltanto su richiesta, in un
contesto Chromium isolato e headless per default, senza profili o cookie utente;
`MockBrowser` non avvia né apre nulla. L'agente accetta task web di ricerca
Google e task locali espliciti (`local: click <testo>` oppure
`local: type <testo> = <contenuto>`). La ricerca inserisce la query ma non
estrae risultati. Rispettare i termini del sito: usare API ufficiali ove richiesto;
non eseguire scraping né aggirare controlli di accesso, CAPTCHA o sistemi
anti-automazione. I ritardi casuali sono solo pacing, non un meccanismo di
elusione. I test della fase non catturano lo schermo né inviano input reali e
non aprono browser.

### Core intellettuale persistente (Fase 1)

`core/intellectual_core.py` espone pianificazione, ricerca, generazione di
bozze, critica e revisione. `core/memory_store.py` salva memoria per scope
(`session`, `project`, `long_term`), record e checkpoint nello stesso SQLite
privato. `core/critic_loop.py` registra due cicli di revisione (v1→v2→v3).
Per impostazione predefinita la ricerca esterna non è configurata: il risultato
dichiara l’assenza di fonti invece di inventarle. Un provider può essere passato
esplicitamente al costruttore per test o integrazione futura.

Le bozze espongono `render()` con obiettivo, indice, contenuto, citazioni datate
e tipizzate, bibliografia, limiti, incertezze e cronologia delle revisioni.
L’attendibilità delle fonti è una stima fornita dal provider tra 0 e 1, non una
misura indipendentemente verificata da Jarvis.
Il punteggio della critica è una metrica checklist: `1 - issue_count / 7`,
limitata all’intervallo 0–1; non rappresenta una misura scientifica di qualità.

### Copilot handoff (Fase 2)

`core/copilot_bridge.py` prepara un pacchetto con il prompt originale, gli hash e
le dimensioni dei file e lo registra nel database SQLite privato solo dopo una
conferma. Il prompt non viene mai scritto o modificato. Se
`prompts/copilot_prompt.md` è vuoto, il bridge restituisce l'errore esplicito
`CopilotPromptEmpty`; se manca, restituisce `CopilotPromptNotFound`. In entrambi
i casi non crea un pacchetto né un record.
I pacchetti sono salvati nella tabella dedicata `copilot_handoffs`, separata
dagli eventi dei workflow così da applicare direttamente l'unicità della chiave
task/hash-prompt/hash-allegati e riprendere il pacchetto dopo un riavvio.

Il prompt cercato per primo è `prompts/copilot_prompt.md`; in alternativa si
possono configurare `prompt_path` in `config/copilot.yaml` o
`JARVIS_COPILOT_PROMPT`. Il file attualmente presente nel checkout è vuoto:
l'utente deve inserirvi il proprio prompt originale. Una volta compilato, non
sono necessarie modifiche al codice.

CLI, con percorsi dei file relativi alla radice del repository:

```powershell
python main.py --copilot-handoff --task "Descrizione del task" --files src\file.py tests\test_file.py
```

In chat/HUD usare la forma:
`passa a Copilot task: Descrizione del task | files: src/file.py, tests/test_file.py`.
Entrambi i flussi mostrano un riepilogo e richiedono conferma. Questa fase
registra soltanto il pacchetto: non invia nulla a Copilot. La registrazione è
idempotente per task, hash del prompt e insieme degli hash degli allegati.

## Documenti

- `docs/n8n/README.md` — configurazione del bridge n8n e workflow "echo" di prova.
- `NOTICE` — attribuzioni e licenze.
- `INSTALL_WINDOWS.md` — guida di installazione.
- `SECURITY.md` — checklist di sicurezza.
- `LIMITI.md` — limiti noti e parti DA VERIFICARE.

## Licenza

Uso **personale / non commerciale**. Componenti sotto CC BY-NC 4.0 (© FatihMakes), GEV MIT, ASTRALIS Apache-2.0. Vedi `NOTICE` e `LICENSE`.
