# Report tecnico — JARVIS / HUD

## Ambito e metodo

Report basato sui sorgenti presenti in questo checkout. I conteggi sono statici: non equivalgono a tool effettivamente caricati o test superati. Non sono stati aperti `config/api_keys.json`, `config/secrets.json`, i JSON runtime in `memory/` o i log. Le chiavi citate sotto sono solo nomi letti dal codice; nessun valore segreto o personale è riportato. Il catalogo MCP di GEV è richiesto al server locale all'avvio, quindi non è stato interrogato in questo report.

## 1. ACTIONS — `actions/*.py`

Il loader considera i file Python non prefissati da `_` e carica quelli che esportano `TOOL`. La conferma della tabella distingue la conferma umana dalla barriera `confirmed=true`: per le action `risk_class="destructive"` il registry richiede quel parametro, ma da solo non prova che una persona abbia confermato. La conferma UI separata è usata da `core.confirm` in altri percorsi; `TaskRunner` pausa invece le fasi write/destructive.

| File | TOOL | Descrizione | Parametri (tipo; * indica required) | Conferma umana | Undo | Piattaforme dichiarate |
|---|---|---|---|---|---|---|
| `app_launcher.py` | `app_launcher` | Cerca e avvia applicazioni Windows con nome, senza accettare percorsi arbitrari. | `name:string*`, `args:string` | No gate UI nel file; registry richiede `confirmed=true` (destructive). | No | Windows (descrizione del tool) |
| `background_monitor.py` | — (helper) | Gestione dei monitor proattivi. | — | — | — | Non dichiarate |
| `browser_control.py` | — (helper) | Operazioni sul browser integrato. | — | — | — | Non dichiarate |
| `code_helper.py` | — (helper) | Helper per richieste di codice. | — | — | — | Non dichiarate |
| `coder_agent.py` | `coder_agent` | Scrive codice in un file a partire da un task e contesto. | `task:string*`, `context:string`, `file_path:string*` | No gate UI dichiarato. | No | Non dichiarate |
| `computer_control.py` | — (helper) | Helper per controllo del computer. | — | — | — | Non dichiarate |
| `computer_settings.py` | — (helper) | Funzioni di impostazione; usa `core.confirm.request` per operazioni specifiche. | — | Sì, quando richiesto dal codice. | Non rilevato nel file | Non dichiarate |
| `connector_call.py` | `connector_call` | Invoca un tool di un connector o skill registrato. | `tool:string*`, `arguments_json:string`, `skill:string` | No gate UI dichiarato. | No | Non dichiarate |
| `connectors_status.py` | `connectors_status` | Elenca stato, scope e tool di connector e skill. | Nessuno | No | No | Non dichiarate |
| `debugger_agent.py` | `debugger_agent` | Esegue un comando e restituisce analisi/suggerimenti sugli errori. | `command:string*`, `cwd:string` | No gate UI nel file; registry richiede `confirmed=true` (destructive). | No | Non dichiarate |
| `desktop.py` | `desktop_control` | Controlla operazioni desktop come wallpaper, organizzazione, elenco e statistiche. | `action:string*`, `path:string`, `url:string`, `mode:string`, `task:string` | No gate UI dichiarato. | No | Non dichiarate |
| `dev_agent.py` | — (helper) | Supporto usato dall'agente di sviluppo. | — | — | — | Non dichiarate |
| `export_stl.py` | `export_stl` | Converte in STL un modello mostrato o selezionato dalla cartella modelli. | `model:string` | No | No | Non dichiarate |
| `file_controller.py` | `file_controller` | Elenca, crea, elimina, sposta, copia, rinomina e legge/scrive file e cartelle. | `action:string*`, `path:string`, `destination:string`, `new_name:string`, `content:string`, `name:string`, `extension:string`, `count:integer` | No gate UI dichiarato. | Sì, registra operazioni reversibili con `push_undo`. | Non dichiarate |
| `file_processor.py` | — (helper) | Elabora file per gli handler di main. | — | — | — | Non dichiarate |
| `flight_finder.py` | `flight_finder` | Cerca opzioni di volo. | `origin:string*`, `destination:string*`, `date:string*`, `return_date:string`, `passengers:integer`, `cabin:string`, `save:boolean` | No | No | Non dichiarate |
| `game_updater.py` | — (helper) | Funzioni di aggiornamento/avvio giochi. | — | — | — | Non dichiarate |
| `generate_3d_model.py` | `generate_3d_model` | Genera un modello 3D da testo o immagine, con backend locale o remoto. | `prompt:string`, `image_path:string`, `image_url:string`, `style:string`, `model_id:string`, `scale:number`, `show:boolean`, `engine:string` | No gate UI dichiarato nella action. | No | Non dichiarate |
| `large_file_reader.py` | `large_file_reader` | Legge file grandi a blocchi e li elabora con un'istruzione. | `file_path:string*`, `instruction:string` | No | No | Non dichiarate |
| `open_app.py` | — (helper) | Handler di compatibilità per l'apertura app. | — | — | — | Non dichiarate |
| `proactive.py` | — (helper) | Logica delle iniziative proattive. | — | — | — | Non dichiarate |
| `proxy_launcher.py` | `proxy_launcher` | Avvia un comando subprocess secondo le policy configurate. | `command:string*`, `cwd:string` | No gate UI dichiarato. | No | Non dichiarate |
| `reminder.py` | `reminder` | Imposta un promemoria temporizzato. | `date:string*`, `time:string*`, `message:string*` | No gate UI dichiarato. | No | Non dichiarate |
| `report_problem.py` | `report_problem` | Aggiunge un report locale per un problema osservato. | `category:string*`, `summary:string*`, `component:string`, `logical_context:string`, `observed:string*`, `expected:string`, `reproduction:string`, `technical_evidence:string`, `example:string`, `impact:string`, `reproducibility:string` | No | No | Non dichiarate |
| `research_agent.py` | `research_agent` | Ricerca documentazione tecnica e riferimenti per un argomento. | `topic:string*` | No | No | Non dichiarate |
| `screen_processor.py` | — (helper) | Cattura/fornisce immagini dello schermo o della camera. | — | — | — | Non dichiarate |
| `search_3d_model.py` | `search_3d_model` | Cerca e scarica un modello 3D pronto. | `query:string*`, `show:boolean` | No gate UI dichiarato nella action. | No | Non dichiarate |
| `send_message.py` | `send_message` | Invia un messaggio tramite una piattaforma configurata. | `receiver:string*`, `message_text:string*`, `platform:string*` | No gate UI dichiarato. | No | Non dichiarate |
| `supervisor_agent.py` | `supervisor_agent` | Pianifica task complessi coordinando agenti di ricerca. | `task:string*` | No | No | Non dichiarate |
| `system_monitor.py` | — (helper) | Metriche e monitoraggio del sistema. | — | — | — | Non dichiarate |
| `task_runner_cancel.py` | `task_runner_cancel` | Annulla il TaskRunner attivo. | Nessuno | No; annulla. | No | Non dichiarate |
| `task_runner_confirm.py` | `task_runner_confirm` | Riprende una fase TaskRunner sospesa. | Nessuno | Sì: il tool è previsto solo dopo l'OK esplicito dell'utente. | No | Non dichiarate |
| `task_runner_start.py` | `task_runner_start` | Pianifica ed esegue un piano di più fasi. | `objective:string*`, `steps:string` (JSON opzionale) | Sì, pausa le fasi write/destructive fino a `task_runner_confirm`. | No | Non dichiarate |
| `task_runner_status.py` | `task_runner_status` | Mostra stato e fasi del TaskRunner. | Nessuno | No | No | Non dichiarate |
| `ui_layout.py` | `ui_layout` | Cambia pannelli, workspace e layout HUD. | `mode:string*`, `workspace:string`, `panel:string`, `visible:boolean`, `floating:boolean` | No | No | Non dichiarate |
| `use_skill.py` | `use_skill` | Trova una skill dichiarativa e ne restituisce la procedura. | `request:string*` | No | No | Non dichiarate |
| `viewer_3d.py` | `viewer_3d` | Controlla globo e modelli 3D: carica, ruota, evidenzia, modifica e mostra parti. | `mode` e campi specifici dell'operazione (fra cui `lat`, `lon`, `model`, `part`, `style`, `on`, `axis`, `position`) | No | No | Non dichiarate |
| `vscode_agent.py` | `vscode_agent` | Richiede un suggerimento al GitHub Copilot CLI; non applica modifiche. | `prompt:string*`, `working_dir:string`, `timeout:integer` | No | No | Non dichiarate |
| `vscode_control.py` | `vscode_control` | Apre VS Code/file/cartelle, terminale o esegue task consentiti. | `action:string*`, `path:string`, `working_dir:string`, `command:string[]`, `timeout:integer` | No gate UI dichiarato; `run_task` valida il comando. | No | `open_terminal` solo Windows; il resto non è dichiarato |
| `weather_report.py` | `weather_report` | Restituisce un bollettino meteo per città. | `city:string*` | No | No | Non dichiarate |
| `web_search.py` | — (helper) | Funzioni di ricerca web/notizie usate da main. | — | — | — | Non dichiarate |
| `youtube_video.py` | — (helper) | Funzioni di ricerca e controllo YouTube usate da main. | — | — | — | Non dichiarate |

`*` parametro obbligatorio nella dichiarazione `TOOL`. Il loader assegna `write` come rischio predefinito; solo `risk_class="destructive"` aggiunge e richiede `confirmed=true`. Questa barriera è un parametro della chiamata modello, non una conferma umana indipendente.

## 2. CORE — `core/`

Ruolo e riferimenti diretti sono ricavati da docstring/import dei sorgenti first-party; “nessun riferimento” significa che non è stato trovato un import diretto fuori dai test, non che il modulo sia inutilizzabile.

| Modulo | Ruolo (1 riga) | Chiamato/importato da |
|---|---|---|
| `__init__.py` | Inizializza il package. | Nessun riferimento diretto |
| `accessibility.py` | OCR, hotkey opzionali e backend di lettura accessibile. | `main.py`, `page_reader.py` |
| `action_loader.py` | Scopre, valida e invoca action `TOOL`. | `main.py`, `actions/vscode_control.py`, `mcp_server.py` |
| `animations.py` | Effetti visivi opzionali Qt. | `ui.py` |
| `api_keys.py` | Recupera la chiave Gemini da SecretStore o fallback compatibile. | `main.py`, `ui.py`, agent e action, `gemini.py`, `registry_cli.py` |
| `audio_devices.py` | Elenca e seleziona dispositivi audio. | `ui.py` |
| `audit_log.py` | Audit append-only per tool e connector. | `connectors.py`, `jarvis_runtime.py`, `skills.py` |
| `avatar.py` | Renderizza l'avatar HUD. | Nessun riferimento diretto first-party rilevato |
| `avatar_mesh.py` | Mesh dell'avatar. | `avatar.py` |
| `browser_interaction.py` | Costruisce payload validati per interazione browser. | `ui.py` |
| `browser_url.py` | Valida e normalizza URL del browser integrato. | `ui.py` |
| `cad_models.py` | Catalogo e download di modelli CAD predefiniti. | `registry_cli.py` |
| `confirm.py` | Mantiene richieste irreversibili in attesa di un input UI umano. | `ui.py`, `actions/computer_settings.py`, `agents/coder_agent.py`, `plugins/ada_computer_use.py` |
| `connectors.py` | Catalogo, stato, scope e lifecycle dei connector. | `connector_call.py`, `jarvis_runtime.py`, `registry_cli.py`, `skills.py`, `skill_router.py` |
| `echo.py` | Riduce il riconoscimento dell'audio riprodotto dal sistema. | `main.py` |
| `gemini.py` | Chiamate Gemini one-shot. | `gemini_chat.py`, `ws_server.py`, `main.py`, `ui.py`, action e agent |
| `gemini_chat.py` | Entry point headless per chat testuale Gemini. | `gemini_chat_window.py`, `ws_server.py` |
| `geo_router.py` | Classifica richieste geografiche/storiche esplicite e instrada GEV. | `main.py` |
| `guardrails.py` | Policy per subprocess, comandi, path, plugin e memoria. | `main.py`, action, `plugin_loader.py`, `widget_registry.py` |
| `hotkey.py` | Implementa push-to-talk a pressione. | Nessun riferimento diretto first-party rilevato |
| `hud_animator.py` | Transizioni HUD e segnale di reload configurazione. | `ui.py`, `registry_cli.py` |
| `hud_bridge.py` | Ponte HTTP/SSE tra Jarvis e HUD HTML. | `main.py` |
| `image_input.py` | Normalizza input immagine locale/remoto per la pipeline 3D. | `generate_3d_model.py`, generatori 3D |
| `input_queue.py` | Accoda testo ricevuto mentre Jarvis è occupato. | Nessun riferimento diretto first-party rilevato |
| `installer.py` | Auto-installer dipendenze MARK XL. | Nessun riferimento diretto first-party rilevato |
| `intent_router.py` | Distingue intenti gioco/file/ambigui per tool sensibili. | `main.py`, `geo_router.py` |
| `issue_reporter.py` | Registra report locali di limitazioni o errori osservati. | `actions/report_problem.py` |
| `jarvis_runtime.py` | Costruisce singleton condivisi per skill e connector. | `main.py`, action connector/skill, `registry_cli.py` |
| `llm_client.py` | Client per LLM locale. | Nessun riferimento diretto first-party rilevato |
| `local_3d_gen.py` | Coordina generazione 3D locale in subprocess. | action generazione, worker, `model_gen.py`, `registry_cli.py` |
| `local_3d_worker.py` | Worker pesante per generazione 3D locale. | `local_3d_gen.py` |
| `make_pc_cad.py` | Costruisce un modello PC multi-parte. | `registry_cli.py`, `viewer3d.py` |
| `mcp_server.py` | Espone le action Jarvis come MCP via stdio. | Nessun import diretto first-party rilevato |
| `mcp_transport.py` | Trasporti MCP per il registro connector. | `jarvis_runtime.py` |
| `mic_diagnostics.py` | Diagnostica locale del microfono. | Nessun import diretto first-party rilevato |
| `model_gen.py` | Generazione modelli tramite Tripo3D. | action generazione, `local_3d_gen.py`, `registry_cli.py` |
| `model_search.py` | Ricerca di modelli GLB già pronti. | `actions/search_3d_model.py` |
| `page_reader.py` | Prepara testo pagina e lettura vocale cancellabile. | `main.py`, `ui.py` |
| `pattern_learner.py` | Apprende preferenze/correzioni 3D locali. | `main.py`, `registry_cli.py` |
| `plugin_loader.py` | Scopre, valida, abilita e invoca plugin. | `main.py` |
| `prompt_3d.py` | Prepara prompt della generazione 3D locale. | `local_3d_worker.py` |
| `prompt_router.py` | Seleziona un profilo di istruzioni per richiesta. | `main.py` |
| `registry_cli.py` | CLI per gestire connector, skill e risorse. | action e moduli 3D |
| `secret_store.py` | Persistenza segreta tramite backend disponibile. | `api_keys.py`, `connectors.py`, `jarvis_runtime.py`, generatori 3D |
| `skill_router.py` | Instrada prima per intent, poi per skill. | `jarvis_runtime.py` |
| `skills.py` | Carica skill dichiarative con divulgazione progressiva. | action skill, runtime e router |
| `stl_export.py` | Converte glTF/GLB in STL. | `actions/export_stl.py` |
| `stt.py` | Backend STT Whisper/Vosk e buffer dettatura. | `main.py`, `mic_diagnostics.py` |
| `task_runner.py` | Esegue piani di tool con checkpoint e pause di conferma. | `main.py`, action task runner |
| `tool_router.py` | Seleziona gli schemi tool da inviare a Gemini per keyword. | `main.py` |
| `tts.py` | Backend text-to-speech. | `accessibility.py` |
| `ui_panels.py` | Stato, preset e persistenza pannelli HUD. | `main.py`, `ui.py`, `actions/ui_layout.py` |
| `undo.py` | Stack condiviso di undo, massimo 10 operazioni. | `main.py`, action `computer_settings.py`/`file_controller.py` |
| `viewer3d.py` | Validazione e supporto comandi del viewer 3D. | `ui.py`, action e generatori 3D |
| `viseme.py` | Mappa testo/audio a forme della bocca dell'avatar. | Nessun riferimento diretto first-party rilevato |
| `voice_transport.py` | Astrazione del trasporto vocale. | Nessun riferimento diretto first-party rilevato |
| `wake_word.py` | Rilevamento locale della wake word. | `main.py`, `ui.py` |
| `widget_registry.py` | Registro widget HUD. | `ui.py`, `widget_renderers.py` |
| `widget_renderers.py` | Renderer QWidget dei widget. | `ui.py` |
| `ws_server.py` | WebSocket locale autenticato per chat e comandi plugin. | Nessun import diretto first-party rilevato |

La mappa dei chiamanti è basata sugli import diretti trovati nel codice Python, non su chiamate dinamiche o importi nei test.

## 3. FLUSSO REALE

1. `main.py` installa le guardie subprocess, richiede la policy, crea `JarvisUI` e `JarvisLive`. `JarvisLive.__init__` chiama `discover_actions` e `discover_plugins`, configura `TaskRunner` e avvia gli hook plugin; il plugin GEV avvia il proprio lifecycle in un thread.
2. `JarvisLive._listen_audio` acquisisce l'audio da `sounddevice`. `route_microphone_audio` lo conserva nel buffer locale se è attiva la dettatura; altrimenti applica l'eventuale wake-word gate e mette i frame in coda. `_send_realtime` invia i frame a Gemini Live con `session.send_realtime_input`.
3. `_receive_audio` riceve trascrizioni input/output, audio e function call. A turno completato salva la trascrizione in UI/HUD, aggiorna contesto/memoria di pattern e chiama `_schedule_geo_route`; il routing GEV automatico richiede intent non `none`, località e confidence almeno `0.7`.
4. Per il testo digitato o inviato dall'HUD, `_on_text_command` aggiunge istruzione dinamica da `PromptRouter`, eventuali hint appresi e testo utente alla sessione Gemini. `PromptRouter` usa `developer_mode`, `strategic_mode`, `quick_command`, `standard_assistant`; `ToolRouter` filtra gli schemi solo con `JARVIS_TOOL_ROUTING=1`, al momento della (ri)connessione. Default: schema completo.
5. Gemini riceve in `_build_config` `TOOL_DECLARATIONS` core, dichiarazioni action e plugin abilitati. Quando restituisce function call, `_execute_tool` richiede la policy, applica `route_tool` e blocca i casi ambigui. Poi esegue uno dei gestori speciali/main, `ActionRegistry`, `PluginRegistry`, memory o `TaskRunner`. I guardrail di comando/path sono applicati dalle funzioni che li invocano; `install_subprocess_guards()` è installato all'avvio.
6. `ActionRegistry` impedisce le action `destructive` se `confirmed` non è `true`; ciò è una condizione sul payload modello, non un click umano. `core.confirm.request` apre invece un banner UI e `resolve()` esegue solo dopo conferma umana. `TaskRunner` sospende le fasi write/destructive fino al tool `task_runner_confirm`. Il tool `undo` usa lo stack condiviso.
7. Main invia `FunctionResponse` a Gemini. `_receive_audio` mette i byte audio in coda; `_play_audio` riproduce e calcola livello PCM, aggiorna `set_speaking`/HUD e `ui.set_audio_level`. La trascrizione output è riportata nel log e nella chat HUD.

Categorie presenti nei router:

- `intent_router`: `game`, `file`, `ambiguous`, `unknown`; per geo/storia `geo`, `history`, `none`.
- `PromptRouter`: `developer_mode`, `strategic_mode`, `quick_command`, `standard_assistant`.
- `ToolRouter` raggruppa tool in `3d`, `flights`, `gev`, `weather`, `reminders`, `messaging`, `connectors`, `files`, `desktop`, `vision`, `browser`, `code`, `home`, `music`, `utility`, `proxy`, `applications`, `games`, `ui`.

## 4. PLUGINS — `plugins/`

Il loader registra i plugin validi, riserva i nomi già usati e consulta `plugins_enabled` a runtime. Il nome tool base coincide con `PLUGIN.name` (salvo `writing_assistant.py`, che espone `gestisci_testo`).

| File/plugin | Funzione dichiarata | Tool |
|---|---|---|
| `ada_cad_printer.py` | Crea script CAD o gestisce slicing/stampa. | `ada_cad_printer` |
| `ada_computer_use.py` | Automazione computer con analisi visiva. | `ada_computer_use` |
| `automation_shortcuts.py` | Salva/esegue sequenze di passi personalizzate. | `automation_shortcuts` |
| `calculator.py` | Calcoli e conversioni. | `calculator` |
| `calendar_agenda.py` | Legge/crea eventi Google Calendar. | `calendar_agenda` |
| `calorie_counter.py` | Registra alimenti e riepiloghi nutrizionali. | `calorie_counter` |
| `clipboard_manager.py` | Legge/scrive/svuota clipboard. | `clipboard_manager` |
| `gemini_chat.py` | Apre la chat testuale separata. | `gemini_chat` |
| `gev_plugin.py` | Controlla il globo e collega i tool MCP GEV. | `gev`, più tool MCP dinamici |
| `kasa_smart_home.py` | Controlla dispositivi Kasa locali. | `kasa_smart_home` |
| `llm_api_bridge.py` | Invia prompt a provider LLM esterni/configurati. | `llm_api_bridge` |
| `password_generator.py` | Genera password e la copia negli appunti. | `password_generator` |
| `pomodoro_timer.py` | Gestisce timer e fasi Pomodoro. | `pomodoro_timer` |
| `qr_code_generator.py` | Genera immagine QR. | `qr_code_generator` |
| `quick_notes.py` | Aggiunge, elenca o elimina note. | `quick_notes` |
| `smart_device_control.py` | Controlla dispositivi via Home Assistant/Hue/MQTT. | `smart_device_control` |
| `spotify_music_control.py` | Controlla riproduzione Spotify. | `spotify_music_control` |
| `streaming_services.py` | Apre/cerca contenuti in Netflix o Prime Video. | `streaming_services` |
| `vscode_web.py` | Apre code-server nel browser integrato. | `vscode_web` |
| `writing_assistant.py` | Migliora testi/file usando il provider configurato. | `gestisci_testo` |

### GEV: MCP, provider, avvio

- `gev_plugin.py` definisce un tool statico `gev` e carica le dichiarazioni aggiuntive dal client MCP come `gev_mcp_<nome>`. La lista è ottenuta con `tools/list` dal server avviato; il numero effettivo è quindi runtime.
- Il server MCP Node include 40 definizioni Core in `src/tools/index.js`; `catalogForSurface(..., "mcp")` esclude le dichiarazioni marcate MCP-off, lasciando 30 tool MCP nel catalogo Core definito dal sorgente. Nomi esposti: `get_earthquakes`, `get_active_fires`, `get_recent_launches`, `aircraft_in_area`, `find_aircraft`, `get_aircraft_track`, `get_aircraft_info`, `vessels_in_area`, `find_vessel`, `get_vessel_track`, `next_satellite_pass`, `satellites_overhead`, `find_cctv_cameras`, `get_cctv_snapshot`, `find_alpr_cameras`, `get_traffic_flow`, `get_weather_map`, `get_recent_imagery`, `find_submarine_cables`, `find_infrastructure`, `get_bhote_koshi_flood`, `get_cyclones`, `get_fire_perimeters`, `get_terrain_height`, `find_military_installations`, `get_map_features`, `situation_brief`, `military_awareness`, `show_in_gods_eye_view`, `panel_request`.
- I moduli provider includono sorgenti per aircraft (OpenSky e ADS-B), vessels/AIS, space (CelesTrak e Launch Library), meteo/vento (GFS e IFS), terrain, traffic, places, Overpass, CCTV, fires, transit, radio e regional data; sono implementati in `gods-eye-view-main/_gev-clone/server/providers/`.
- All'avvio plugin usa il Node portatile `gods-eye-view-main/_gev-clone/.node/node.exe`. Se `node_modules` manca, esegue `npm ci`; poi lancia Vite su `127.0.0.1:4173`, verifica l'health check e avvia `server/mcp/stdio.js --api-base http://127.0.0.1:4173`. Il client MCP parla stdio/JSON-RPC; le funzioni dati consultano il server GEV locale via HTTP.

## 5. DASHBOARD — `dashboard/`

Il server FastAPI/Uvicorn usa porta `8000`, host `0.0.0.0`; se sono presenti i certificati configura HTTPS e server alias su `8001`. La cifratura applicativa dichiarata è AES-256-CBC: SHA-256 della session key concatenata al salt sorgente produce la chiave; il payload cifrato è base64 di IV da 16 byte seguito da ciphertext con padding PKCS7.

| Rotta | Funzione |
|---|---|
| `GET /static/crypto.js` | Serve CryptoJS locale o redirect CDN se manca. |
| `GET /login`, `GET /` | Pagina login/dashboard. |
| `POST /login` | Scambia PIN temporaneo valido per token di sessione. |
| `GET /auto-login` | Pairing QR con chiave temporanea. |
| `POST /api/device-login` | Rinnova token per device già associato. |
| `POST /api/revoke-devices` | Revoca le associazioni persistenti (autenticato). |
| `POST /api/command` | Accoda testo comando e richiama wake callback (autenticato). |
| `POST /api/wake` | Richiama wake callback. |
| `WS /ws/phone-audio` | Inoltra frame PCM del microfono a una coda per Gemini Live. |
| `POST /api/upload` | Salva file con nome ripulito e limite di 500 MB; richiede `python-multipart`. |
| `GET /api/files`, `GET /uploads/{filename}` | Elenca e scarica file caricati. |
| `WS /ws` | Chat/comandi remoti autenticati; conserva fino a 300 eventi e invia gli ultimi 50 alla connessione. |

PIN/chiavi temporanee sono in memoria e hanno expiry di 600 secondi. Il login restituisce token casuale; per QR il browser riceve un device token persistente e lo invia a `/api/device-login`. Token e associazioni vivono negli insiemi/dizionari del processo. Il browser può inviare testo in chiaro o campo `enc`; per `enc` il backend deriva la chiave dalla session key associata al token. Controlli possibili dal codice: invio comando, wake, audio microfono, upload/download file, revoca device e chat WebSocket.

## 6. UI REALE — `ui.py`

- `MainWindow` compone header, area centrale, footer e dock laterali: `controls` (sinistra), `activity_log` e `input` (destra). L'area centrale contiene `HudCanvas` e uno stack per camera, GEV, browser integrato e chat Gemini; sotto c'è un pannello contenuto separato da `QSplitter`.
- HUD nativa `HudCanvas`: volto/avatar centrale, alone, anelli/archi, scanner, particelle, waveform e testo stato. Il codice ha inoltre `QWebEngineView` per browser/GEV/HUD HTML; quindi il renderer nativo non è l'unico pannello centrale.
- Pannelli/widget principali: barre metriche e gauge (`MetricBar`, `HudGauge`), log, input/file-drop, camera preview, Plugin Manager, `ConfirmBanner`, selettore dispositivi audio, memoria, clipboard, remote-control overlay, setup e personalizzazione colori/voce.
- Stati animati HUD definiti da `HudAnimator`: `idle`, `listening`, `thinking`, `speaking`, `error`, `generating_3d`; la UI mostra inoltre `PROCESSING` e `MUTED`. Riduzione animazioni con `JARVIS_REDUCED_MOTION=1`.
- Palette sorgente `C`: sfondo `#00060a`, pannelli `#010d14`/`#010f18`, bordo `#0d3347`, ciano primario `#00d4ff`, arancione `#ff6b00`, giallo `#ffcc00`, verde `#00ff88`, rosso `#ff3355`, testo chiaro `#8ffcff`. Font UI indicato nei widget: `Courier New`.
- Animazioni osservabili nel codice: impulsi concentrici, archi rotanti, scanner, respirazione/alone, particelle, waveform legata al volume audio, transizioni colore e glow. Il canvas usa timer Qt e limita gli aggiornamenti secondo `JARVIS_UI_FPS`.
- Workspace persistenti dichiarati: `full`, `focus`, `coding`, `recon`; dock e pannelli possono essere mostrati, nascosti o flottati.

## 7. MEMORIA

**Non letti i JSON runtime.** La struttura seguente è derivata da `memory_manager.py` e `pattern_learner.py`.

- `memory/long_term.json`: categorie iniziali `identity`, `preferences`, `projects`, `relationships`, `wishes`, `notes`; ogni entry è `{value, updated}`. Il codice può inoltre aggiungere `sessions` per riepiloghi.
- Prompt memory: include identity, entries recenti entro budget, poi indice dei soli nomi/chiavi rimasti fuori. `recall_memory` (`search_memory`) scansiona in memoria categorie, chiavi e valori con punteggio lessicale, non usa embeddings né indice file.
- `memory/learned_patterns.json`: oggetto con chiave `patterns`; i record validati contengono `id`, `type`, `context`, `observation`, `confidence`, `occurrences`, `last_seen`. Tipi: `style_preference`, `tool_failure`, `correction`, `app_launch`; massimo 100 record.
- Indicizzazione file: non ho trovato una pipeline di indicizzazione persistente nei moduli esaminati. `file_controller` cerca ricorsivamente nel filesystem quando viene chiamato (`Path.rglob`); l'indice descritto in `memory_manager` riguarda le chiavi della memoria, non i file.

## 8. ESTENSIONE VS CODE — `../jarvis-vscode-extension/`

- Comandi registrati: `jarvis.openPanel` e `jarvis.setConnectionToken`. Fornisce inoltre language model tool `jarvis_ask`.
- Il client si connette a `ws://127.0.0.1:<porta>`, porta configurazione `jarvis.wsPort`, default `8765`. Token salvato in VS Code `SecretStorage`; il sorgente supporta anche `JARVIS_WS_TOKEN` e migrazione della vecchia impostazione utente.
- Protocollo: WebSocket invia prima `{type:"auth", token}`; dopo `auth_ok` usa `ping`/`pong` e messaggi `chat` con id/testo/history; il server risponde con `status` e `reply`. La UI chat invia richieste a Gemini tramite `core.ws_server`.
- `core/ws_server.py` ascolta solo loopback e controlla il token; supporta `chat` e `command` per un `plugin_registry`. Nel checkout main non importa né avvia `ws_server`; il README dell'estensione richiede di avviare sia app sia servizio locale. Pertanto la presenza del server e dell'estensione non prova che il bridge sia attivo automaticamente.

## 9. VARIABILI D'AMBIENTE E CONFIG

### Variabili `JARVIS_*` runtime

| Variabile | Default nel codice | Significato |
|---|---|---|
| `JARVIS_3D_BACKEND` | `triposr` | Backend locale `triposr` o `sf3d`; valori non riconosciuti ricadono su TripoSR. |
| `JARVIS_3D_CACHE` | `1` | Abilita cache modelli; `0` la disabilita. |
| `JARVIS_3D_CACHE_MAX_GB` | `5` | Limite cache in GB. |
| `JARVIS_3D_CACHE_TTL_DAYS` | `30` | TTL cache in giorni. |
| `JARVIS_3D_CANDIDATES` | `3` | Numero candidati generati, clamp 1–6. |
| `JARVIS_3D_DEBUG_DIR` | non impostata | Cartella debug; le immagini debug sono scritte solo se impostata. |
| `JARVIS_3D_HALF` | `1` | Abilita half precision; `0` la disabilita. |
| `JARVIS_3D_PYTHON` | interprete corrente | Interprete worker locale 3D; export STL cerca anche gli interpreti venv. |
| `JARVIS_3D_REMBG` | `isnet-general-use` | Modello rembg. |
| `JARVIS_3D_SF3D` | `stabilityai/stable-fast-3d` | Identificatore modello SF3D. |
| `JARVIS_3D_TEXT2IMG` | `stabilityai/sd-turbo` | Identificatore text-to-image. |
| `JARVIS_3D_TEXTURE` | `512` | Risoluzione texture. |
| `JARVIS_3D_TRIPOSR` | `stabilityai/TripoSR` | Identificatore modello TripoSR. |
| `JARVIS_ACCESSIBILITY_HOTKEYS` | non impostata (off) | Opt-in hotkey globali; abilitate da `1`, `true`, `yes`, `on`. |
| `JARVIS_ALLOW_PLAINTEXT_KEY` | non impostata (off) | `1` consente il salvataggio plaintext nel flusso di setup chiavi. |
| `JARVIS_APP_LAUNCHER` | `1` | `0` disabilita app launcher. |
| `JARVIS_GEV_PORT` | `4173` se non fornita | Override porta GEV letta dalla UI. |
| `JARVIS_PATTERN_LEARNER` | `1` | `0` disabilita l'apprendimento locale dei pattern. |
| `JARVIS_PROBLEM_REPORT_PATH` | percorso Desktop Windows definito in `core/issue_reporter.py` | Override file report problemi. |
| `JARVIS_REDUCED_MOTION` | non impostata (off) | `1` riduce/limita animazioni UI. |
| `JARVIS_STL_DIR` | `Documents/Jarvis/STL` (fallback `Documenti`) | Directory export STL. |
| `JARVIS_TOOL_ROUTING` | `0` | `1` abilita la selezione keyword dei tool inviati a Gemini. |
| `JARVIS_UI_FPS` | `30` | Frequenza UI impostata dal canvas. |
| `JARVIS_UI_LAYOUT` | `config/ui_layout.json` | Override file layout. |
| `JARVIS_WS_TOKEN` | nessun default; usa SecretStorage/impostazione migrata | Override token lato Extension Host. |

Le variabili test-only trovate sono `JARVIS_RUN_REAL_WEBENGINE` e `JARVIS_TEST_APPLE_GLB`; non sono impostazioni runtime dell'applicazione.

### Chiavi config note dal codice

- `config/api_keys.json` (solo nomi letti/scritti dal codice): `gemini_api_key`, `assistant_name`, `user_name`, `voice_name`, `morning_brief_enabled`, `input_device`, `output_device`, `plugins_enabled`, `ws_token`, `os_system`. Il valore di `gemini_api_key` e quello di `ws_token` non sono riportati.
- `config/voice_settings.json`: `page_reader_engine`, `page_reader_speed`, `wake_word_enabled`, `full_duplex_enabled`.
- Schema di layout definito dal codice: `version`, `workspace`, `panels`, `floating`, `qt_state`, `geometry`.
- Config HUD definite dal loader: `hud_states.json` contiene `states` con i campi `core_color`, `ring_speed`, `waveform_amplitude`, `glow_intensity`, `particle_count`; `hud_transitions.json` contiene `default_duration` e `transitions`.
- `secrets.json` è usato da `SecretStore`; il contenuto non è stato aperto. I JSON di stato presenti nella cartella config non sono stati letti.

## 10. NUMERI

Conteggio statico nel checkout:

| Elemento | Numero / misura |
|---|---:|
| Dichiarazioni core in `main.py` | 29 |
| File action Python | 42 |
| File action con `TOOL` | 28 |
| File action helper senza `TOOL` | 14 |
| File plugin Python | 25 |
| Plugin con `PLUGIN` dichiarato | 20 |
| Tool plugin GEV MCP | 30 nel catalogo MCP Core del sorgente; nomi aggiuntivi letti dal server a runtime |
| File `test_*.py` | 56 |
| Funzioni/metodi `test_*` contati via AST | 514 |

Righe fisiche Python (inclusi commenti e righe vuote):

| Cartella | Righe |
|---|---:|
| `actions/` | 12.624 |
| `core/` | 13.058 |
| `plugins/` | 4.299 |
| `dashboard/` | 883 |
| `memory/` | 821 |
| `tests/` | 11.332 |

Dipendenze principali in `requirements.txt`: PyQt6/QtWebEngine, `google-genai`, `sounddevice`, `numpy`, Pillow, `requests`, `ddgs`, Playwright, `pyautogui`, `pygetwindow`, OpenCV, `mss`, `pytesseract`, `psutil`, `send2trash`, FastAPI/Uvicorn, `cryptography`, `python-multipart`, `python-kasa`, `websockets`, `pyttsx3`, `qrcode`; dipendenze Windows condizionali includono `comtypes`, `pycaw`, `pywinauto`, `pywin32`, `keyboard`, `win10toast`. `requirements-optional.txt` include `faster-whisper` e `tripo3d`.

I conteggi test/tool sono conteggi di sorgente, non esecuzioni o cataloghi caricati. In particolare i 30 MCP GEV sono il filtro della surface MCP sui tool Core; il plugin Python ottiene la disponibilità concreta interrogando il server locale.

## 11. STATO

### Implementato nel codice

- Audio Gemini Live, trascrizioni, playback, interruzione, wake-word opt-in e dettatura locale opzionale.
- Caricamento dinamico delle action/plugin, tool routing, routing intent gioco/file e geo/storia.
- Guardrail per subprocess/path, memoria long-term, pattern learner, conferma UI, stack undo e TaskRunner con approvazione delle fasi.
- HUD Qt, viewer 3D/browser/chat incorporati, pannelli configurabili, Plugin Manager e bridge HUD HTML.
- Dashboard HTTP/WebSocket e server WebSocket locale per l'estensione, ciascuno con implementazione propria.
- Plugin GEV: avvio/health-check Node/Vite e bridge MCP stdio; i tool MCP dipendono dal catalogo restituito dal processo locale.

### Incompleto, opzionale o non collegato automaticamente

- `plugins/_ada_computer_use.py` dichiara esplicitamente un placeholder legacy non implementato; il nome con `_` lo esclude dalla discovery ordinaria. Il plugin separato `ada_computer_use.py` è un modulo diverso.
- Il server `core.ws_server` esiste ma non è importato/avviato da `main.py`; l'estensione richiede quindi il servizio locale attivo per collegarsi.
- Whisper, Tripo3D/SF3D, backend TTS/accessibilità e alcune integrazioni dipendono da pacchetti, modelli, hardware o credenziali opzionali.
- `core/connectors.py` e `core/widget_renderers.py` contengono metodi astratti che sollevano `NotImplementedError`; sono punti di estensione, non prova di un TODO per ogni connector o widget.
- La ricerca di sorgenti Python non ha trovato una pipeline persistente di indicizzazione file; il codice della memoria costruisce invece un indice lessicale di chiavi di memoria.
- Non ho eseguito pytest per produrre questo inventario; i numeri riportati sono conteggi statici AST/file.
