# LOOP: TaskManager e orchestrator-worker

## Goal
Completare l'orchestrazione dei task JARVIS in modo verificato, senza integrazione fuori dallo scope approvato e senza alterare modifiche preesistenti.

## Memoria

### Ciclo 1
- Data/ora: 2026-11-08 11:32 +01:00
- Tentativo N: 1
- Cosa ho cambiato: corretto `core/task_manager.py` separando l'avvio del manager (`start`) dall'avvio dei worker (`start_task`); aggiornati i test per il nuovo lifecycle.
- Esito della verifica: `pytest -q tests/test_task_manager.py` — 16 passed; Ruff e `git diff --check` puliti.
- Cosa ho imparato: lo shutdown deve terminalizzare i worker running ma lasciare persistenti i task pending; altrimenti il roundtrip di persistenza altera lo stato.

### Ciclo 2
- Data/ora: 2026-11-08 11:36 +01:00
- Tentativo N: 1
- Cosa ho cambiato: aggiunti `core/worker_llm.py` con client Gemini asincrono, system prompt isolato e chiusura esplicita, e `tests/test_worker_llm.py` con client mock.
- Esito della verifica: `pytest -q tests/test_worker_llm.py` — 7 passed; Ruff e `git diff --check` puliti. `mypy` non e' installato nell'ambiente.
- Cosa ho imparato: la versione di `google-genai` installata espone `client.aio.models.generate_content` e `client.aio.aclose`; nessuna chiamata API reale e' stata eseguita.

### Ciclo 3
- Data/ora: 2026-11-08 12:07 +01:00
- Tentativo N: 1
- Cosa ho cambiato: collegati `TaskManager`, `TaskOrchestrator`, `WorkerLLM`, `WriterWorker` e `BrowserWorker` a `main.py`; aggiunti il gate idle per gli input vocali/testuali, l'iniezione delle notifiche raggruppate solo a JARVIS idle, il relay task verso SSE/HUD, gli endpoint locali per i risultati e i pallini cliccabili in chat. Documentati ruoli, cancellazione e percorso JSON.
- Esito della verifica: suite mirata task/HUD/browser/UI — 204 passed, 7 skipped; Ruff pulito per nuovi moduli e test, nessun errore Ruff sulle righe modificate di `main.py` e `core/hud_bridge.py`; sintassi inline JavaScript, parsing Python e `git diff --check` passati.
- Cosa ho imparato: in alcune esecuzioni Windows `os.replace` nella directory temporanea pytest ha restituito `PermissionError` intermittenti; i test isolati e l'ultima suite completa sono passati. Non e' stato introdotto un retry o un workaround di temporizzazione, per mantenere il contratto atomico approvato.

### Ciclo 4
- Data/ora: 2026-11-08 12:51 +01:00
- Tentativo N: 1
- Cosa ho cambiato: in `core/task_manager.py`, eccezioni del worker ora portano a `failed` immediato, risultati non stringa falliscono con `worker_contract_violation`, errori di `complete()` sono gestiti separatamente e le cancellazioni asyncio restano distinte; la persistenza ritenta `os.replace` dopo PermissionError. Aggiunti quattro test di regressione in `tests/test_task_manager.py`.
- Esito della verifica: test mirati nuovi — 4 passed; `pytest -q tests/test_task_manager.py` — 20 passed; lo script standalone ha stampato `status=failed error=worker_contract_violation: expected str, got NoneType`; Ruff, parsing JavaScript HUD (`ok 2`) e `git diff --check` passati.
- Cosa ho imparato: il risultato `None` veniva completato come eccezione non recuperata dopo il ramo di gestione errori worker; validarlo prima di chiamare `complete()` evita il task bloccato fino al watchdog. La verifica di retry usa una sostituzione che fallisce due volte, poi riesce, senza attese reali.

## LOOP: Prompt Live durante reconnect Iris

### Ciclo 1
- Data/ora: 2026-11-08 14:13 +01:00
- Tentativo N: 1
- Cosa ho cambiato: in `main.py`, gli invii HUD Live attendono una sessione pronta, sono serializzati e riportano gli errori asincroni sia nel log sia nella chat HUD. In `tests/test_hud_bridge_integration.py`, aggiunti test per la disponibilita' dopo reconnect, la serializzazione di prompt ravvicinati e la segnalazione degli errori.
- Esito della verifica: `pytest -q tests/test_hud_bridge_integration.py tests/test_gev_plugin.py` — 30 passed; suite non-live — 1233 passed, 10 skipped, 5 deselected, 4 xfailed; Ruff sui test e `git diff --check` passati.
- Cosa ho imparato: il callback UI poteva continuare a usare la sessione Live durante il reconnect; il future non atteso nascondeva gli errori di invio. La verifica automatica copre reconnect e invii concorrenti, ma non dimostra l'apertura visiva di GEV in un'esecuzione desktop reale.

## LOOP: Test manuali principali Jarvis

### Test 1 — Avvio e caricamento
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: verificati percorso, configurazione e stato del worktree; non eseguito `python main.py`.
- Esito: SKIPPED.
- Nota: `config/api_keys.json` e' popolato; l'avvio apre una sessione Gemini. Non essendo arrivata conferma per traffico esterno, UI e messaggio ready restano non verificati.

### Test 2 — Chat testuale
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: verificati codice e database senza inviare un prompt.
- Esito: SKIPPED.
- Nota: il prompt di prova verrebbe trasmesso a Gemini. Nel DB disponibile non ci sono chiavi chat persistite.

### Test 3 — Plugin GEV
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: `pytest -q tests/test_gev_plugin.py`; controllo della disponibilita' di Node.
- Esito: PASS offline, 9 passed.
- Nota: Node e' presente; il plugin non e' stato avviato nella UI, quindi il runtime effettivo non e' stato provato.

### Test 4 — Skill
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: ispezione dei file `skills/*/SKILL.md` e `pytest -q tests/test_connectors_skills.py tests/test_live_action_wiring.py tests/test_gev_mcp_client.py`.
- Esito: PASS offline, suite combinata 44 passed.
- Nota: esistono quattro skill dichiarative; il tool non e' stato invocato in una sessione Live.

### Test 5 — Database SQLite
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: query SQLite in modalita' read-only sul DB configurato; `PRAGMA quick_check`, elenco tabelle e conteggi senza leggere contenuti utente.
- Esito: PASS, `quick_check=ok`.
- Nota: presenti tabelle workflow/memoria; assenti `conversations`, `chat_sessions`, `chat_interactions`. `jarvis_memory` e' vuota.

### Test 6 — Azioni built-in e tool core
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: `pytest -q tests/test_action_loader.py tests/test_tool_router.py tests/test_geo_router.py tests/test_prompt_router.py tests/test_plugin_sandbox.py`.
- Esito: PASS offline, 40 passed; prova di azioni reali SKIPPED.
- Nota: nessun programma e' stato aperto e nessun comando computer-control/web e' stato eseguito.

### Test 7 — Routing e dispatch
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: test offline di action loader, tool router, geo/prompt router, wiring e GEV MCP.
- Esito: PASS offline, suite combinate rispettivamente 40 e 44 passed.
- Nota: il routing nel runtime Live non e' verificato senza avvio/autorizzazione di rete.

### Test 8 — Log e memoria
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: scansione delle firme `Traceback`, `CRITICAL`, `Unhandled exception` nei log disponibili; test `pytest -q tests/test_chat_orchestrator.py tests/test_memory_store_pool.py`; controllo read-only DB.
- Esito: PASS limitato, zero firme trovate nei due log; 12 test passati; DB integro.
- Nota: `jarvis_memory` non contiene righe; la scansione delle firme non e' una revisione semantica completa e non dimostra che l'app sia stata avviata durante questa prova.

### Report
- Data/ora: 2026-11-08 14:15 +01:00
- Azione eseguita: creato `TEST_REPORT.md` con risultati, evidenze, anomalie, limiti e raccomandazioni.
- Esito: completato con stato complessivo PARZIALE.
- Nota: le prove esterne/UI sono state lasciate non eseguite in assenza di autorizzazione; inoltre il repository locale non coincide con il nome del repository indicato nella richiesta.

## LOOP: Confronto statico GEV tra new-era e new-gen

- Data/ora: 2026-11-08 15:48 +01:00
- Azione: confronto read-only dei percorsi `_build_config`, `get_tool_declarations`, `get_extra_tool_declarations`, avvio plugin, screenshot e `npm ci` nei due checkout; `git fetch origin main` sul checkout `jarvis-vii-app`.
- Esito: il percorso sincrono delle dichiarazioni GEV e l'attesa `Event.wait` fino a 690 s coincidono nei due checkout; `start_all` è avviato in entrambi nel thread `gev-start`; `npm ci` ha timeout 600 s in entrambi. Nel runtime `new-era`, al contrario di `new-gen`, `core.viewer3d.save_screenshot` è presente.
- Providers: in `new-era` `_build_config()` raccoglie ancora sincronicamente le dichiarazioni tool plugin; il percorso providers non le sostituisce. Il rischio di blocco dell'event loop durante startup/reconnect è trasferibile come ipotesi, non confermato come causa del freeze.
- Aggiornamento remoto: remote `origin` è `jarvis-new-era`; HEAD `677f153` sul branch `fix/log-redaction`; `origin/main` dopo fetch è `44e9336`, 10 commit dietro HEAD e senza commit avanti. Upstream non configurato. Worktree preesistente preservato.
- Limiti: non avviati app o GEV; nessun log letto; nessuna cattura durante freeze. Il dump precedente del PID 20940 rimane non diagnostico.
- Memoria/report: aggiunta la comparazione a `TEST_REPORT.md`. Nessun codice applicativo modificato, nessun commit/push.

## LOOP: Test manuale chat JARVIS

- Data/ora: 2026-11-08 15:56 +01:00
- Azione: avviato `.venv\Scripts\pythonw.exe main.py` nel checkout `jarvis-vii-app` @ `677f153` (PID 2520); inviato un prompt breve alla chat HUD/Live e due prompt innocui al pannello Gemini testuale.
- Esito HUD/Live: il prompt è stato visualizzato nella chat ma non è arrivata una risposta entro ~60 secondi; test non riuscito/inconclusivo. Non è stato possibile attribuire la causa.
- Esito pannello Gemini: il primo tentativo è terminato con `504 DEADLINE_EXCEEDED`; il secondo con `503 UNAVAILABLE` per alta domanda del modello. Nessuna risposta generata.
- Recupero UI: entrambi gli errori sono stati presentati chiaramente; stato di errore recuperabile e input/`SEND` nuovamente abilitati. Processo UI ancora attivo dopo i test.
- Verifica automatizzata: `python -m pytest -q tests/test_gemini_chat_headless.py tests/test_gemini_chat_ui.py tests/test_ui_input.py` — 26 passed.
- Tentativo diagnostico: `py-spy dump --pid 2520` non ha potuto leggere lo stack (`Failed to find python version from target process`).
- Decisione: nessun fix applicato perché il provider ha restituito errori espliciti 503/504 e i test UI confermano la gestione/resilienza; retry automatici non aggiunti senza prova di un bug applicativo. Serve verificare il provider più tardi e diagnosticare separatamente il percorso HUD/Live.
- Report: aggiunta sezione chat UI a `TEST_REPORT.md`. Nessun commit/push.

## LOOP: Fix e test conversazione Gemini

- Data/ora: 2026-11-08 16:20 +01:00
- Analisi: il pannello chat chiamava un solo modello (`gemini-3.8-flash`) invece della ladder del modulo condiviso. Test reali precedenti: errori provider 504 e 503. Il modello 2.5-flash usato dalla ladder FAST ha restituito 404 per questa configurazione; `gemini-3.7-flash` ha restituito 503. La ladder FAST ha invece risposto via Live in 4,83 s.
- Tentativo 1 (fallback): introdotta una ladder chat su Live e modelli REST 3.x disponibili, cronologia serializzata in prompt compatibile con Live ed errori aggregati espliciti. La prima risposta reale è arrivata in 3,34 s, ma affermava “non JARVIS”: individuato che il Live one-shot imponeva la persona “data-processing function”.
- Tentativo 2 (persona): aggiunta una persona conversazionale specifica per la ladder CHAT, lasciando invariato il comportamento one-shot degli altri tool; aggiunta system instruction del pannello per le chiamate REST. Test reale ha risposto “Sono JARVIS, al tuo servizio per aiutarti con quello che ti serve.” in 7,13 s.
- Test UI end-to-end: app riavviata con il codice aggiornato (PID 504). Due messaggi inviati e risposti; il secondo ha recuperato “Ada” dal primo turno.
- Test automatici: `pytest -q tests/test_gemini_chat_headless.py tests/test_gemini_chat_ui.py tests/test_ui_input.py` — **28 passed**; `compileall` e `git diff --check` passati.
- Esito: **PASS per chat testuale dedicata**. La chat ora usa fallback e mantiene contesto/persona. La chat vocale HUD/Live non è stata risolta né verificata da questo fix.
- Modifiche: `core/gemini.py`, `core/gemini_chat.py`, `tests/test_gemini_chat_headless.py`, più report/memoria. Nessun commit/push.

## LOOP: Verifica chat principale HUD/Live

- Data: 2026-11-08
- Ambito: chat principale JARVIS nell'HUD, senza aprire il pannello Gemini dedicato e senza usare la conversazione Ada.
- Avvio finale: `.venv\Scripts\pythonw.exe main.py`, checkout `jarvis-vii-app` @ `677f153`, PID 26460. Endpoint HUD `http://127.0.0.1:8765/` verificato HTTP 200; processo ancora attivo.
- Prove dalla chat HUD: risposta corretta a `quanto fa 2 + 2?` (4), follow-up `E quanto fa più 3?` (7), e `Qual è la capitale d'Italia?` (Roma). Le risposte sono state mostrate nell'interfaccia entro pochi secondi.
- Log applicativi: callback HUD registrati come `INPUT_START` / `INPUT_HANDLER_OK`; nessuna eccezione osservata. Log temporanei rimossi dopo la verifica.
- Esito: **PASS per i tre turni testuali HUD/Live**; il mancato riscontro riportato nel test precedente non è stato riprodotto dopo il riavvio. Non prova il percorso microfono/audio e non identifica la causa storica del precedente mancato riscontro.
- Decisione: nessun fix al codice runtime, perché il difetto non è stato riprodotto. I test automatizzati precedenti riguardano soprattutto il pannello dedicato; non sono stati rilanciati in questa verifica senza modifiche al codice. Report aggiornato in `TEST_REPORT.md`; nessun commit/push.

## LOOP: Riproduzione comando YouTube + GEV

- Data: 2026-11-08
- Avvio: `pythonw.exe -u main.py` nel checkout `jarvis-vii-app` @ `677f153`, PID 24136; HUD HTTP 200.
- Comando nel campo chat principale: `Apri YouTube e poi God Eye View`.
- Conferma dai log non bufferizzati: tool `open_website` completato con `Opening the website inside Jarvis.`, seguito dal tool plugin `gev` con `action=open` e risultato `Apro God's Eye View, signore.`. La pagina GEV è stata aperta e caricata.
- Esito: nessun blocco riprodotto; la risposta è arrivata e il processo è rimasto attivo dopo il dispatch.
- Limite: il comando è stato inviato come testo nell'HUD, non tramite microfono. È stata verificata la sequenza Live di dispatch dei due tool, non la cattura vocale o la riproduzione audio che facevano parte del sintomo originario. Nessuno stack di freeze disponibile perché il blocco non si è verificato.
- Decisione: nessuna modifica al runtime; log temporanei rimossi; report aggiornato in `TEST_REPORT.md`.

## LOOP: File implementativo piattaforma modulare

- Data: 2026-11-08
- Obiettivo: tradurre il principio “un cervello orchestratore, interfacce esplicite, provider sostituibili, UI opzionale” in un piano eseguibile per il checkout `jarvis-vii-app`.
- Diagnosi: verificati i contratti `Engine`/`LLM`/`STT`/`TTS` in `providers/base.py`, il registry, `core/outcome.py`, `core/secret_store.py`, `core/memory_store.py`, sandbox, agenti, server headless e adapter n8n. `kernel/`, `capabilities/` e `orchestrator/` non esistono ancora; `main.py` coordina il runtime e alcuni agenti importano dipendenze concrete da `core/`.
- File creati/aggiornati: `docs/impl/IMPL-ARCH-001-piattaforma-modulare.md`; indice `docs/impl/ROADMAP.md`; questa memoria.
- Procedura: definiti milestone A0-A6 con dipendenze, test di baseline/contratto, guardrail, realtime desktop, persistenza compatibile, UI opzionale e rimozione legacy solo a migrazione conclusa.
- Fattibilità F4: **GO CON MODIFICHE** per una migrazione incrementale; **NO-GO** per riscrittura big-bang. La baseline A0 e l'isolamento del worktree già sporco devono precedere il codice.
- Verifica: controllo statico di file e test già esistenti; nessun codice runtime modificato. Essendo un piano, non sono stati eseguiti test applicativi.
- Stato: F1-F4 completate per la progettazione; F5-F8 restano da eseguire per ogni milestone. Nessun branch o commit creato.

## LOOP: A0 baseline e A1 kernel minimo

- Data: 2026-11-08
- Preservazione: registrato il worktree preesistente su `fix/log-redaction` @ `677f153`; nessuna modifica esistente è stata ripulita o sovrascritta.
- A0: i sette test di confine (`test_provider_contracts`, `test_plugin_sandbox`, `test_memory_store_pool`, `test_n8n_bridge`, `test_n8n_outbox`, `test_server`, `test_agent_loop`) hanno dato **80 passed in 11.43s** prima delle modifiche A1. Il primo tentativo non aveva il working directory corretto e pytest non aveva eseguito test; rilanciato dalla root giusta.
- Warning osservato: pytest-asyncio segnala che `asyncio_default_fixture_loop_scope` non è impostato. Il warning precedeva le modifiche A1 e non blocca il test; non è stato cambiato un config non correlato.
- A0 live/performance: non sono state misurate 30 sessioni né provati microfono, interrupt o latenza primo chunk; stato **DA VALIDARE LIVE**.
- A1 file aggiunti: `capabilities/contracts.py` (tool call/reply con status esplicito e mapping read-only), `capabilities/providers.py` (re-export che conserva l'identità di `Engine`, `LLM`, `STT`, `TTS`), `kernel/events.py` (pub/sub async con unsubscribe, chiusura ed errori aggregati), `kernel/lifecycle.py` (start ordinato, shutdown inverso, rollback anche del componente il cui start fallisce), `kernel/config.py` (config pubblica validata, senza copiare segreti), package exports e `tests/test_kernel_primitives.py`.
- Test A1+regressione: **90 passed in 8.23s** sul set A0 più i nuovi test. `compileall` del nuovo kernel/capabilities e Ruff superati al termine delle correzioni. Il runner ha continuato a segnalare solo il warning pytest-asyncio già osservato.
- Esito A1: **PASS per primitive isolate**, non ancora integrate. Non toccati `main.py`, provider concrete, UI, agenti o guardrail; nessuna affermazione di convalida vocale, latency o runtime headless completo.
- A2 file aggiunti: `orchestrator/conversation.py` con streaming LLM iniettato, cronologia di sessione in memoria, serializzazione dei turni, eventi opzionali, rifiuto esplicito dei tool call non ancora coperti da policy e rollback dello stato su errore provider; test `tests/test_headless_conversation.py`.
- Test A0-A2 combinati: **100 passed in 8.96s**. `compileall` su `kernel capabilities orchestrator`, Ruff selettivo e `git diff --check` passati. È stato verificato in un sottoprocesso che importare l'orchestrator non carica PyQt6 o `google.genai`.
- Esito A2: **PASS per il primo use case headless**, non per il milestone completo. L'orchestrator non è collegato a `main.py`, Gemini Live o UI; non sceglie i provider, non persiste conversazioni e rifiuta tool call fino all'implementazione della policy.
- Prossimo step A2: progettare bootstrap/factory, poi decidere come collegare il runtime senza sovrascrivere le modifiche locali già presenti. Voce, provider reale, interruzione e performance rimangono `DA VALIDARE LIVE`. Nessun commit o branch creato.

## LOOP: A3 primo plugin Computer

- Data: 2026-11-08
- Obiettivo: migrare un solo agente dietro capability neutrali e dipendenze iniettate, lasciando intatto il controllo desktop legacy.
- Modifiche: `capabilities/computer.py` definisce le porte per visione, input desktop e ricerca web; `agents/computer_agent.py` non importa più `core/` e richiede tutte le capability via constructor injection. `agents/__init__.py` ora mantiene gli export ReAct legacy caricandoli pigramente, così importare `agents.computer_agent` non carica gli altri agenti/core. Aggiunti `agents/contracts.py` e `agents/computer_plugin.py`: il plugin accetta solo `computer_task`, richiede un `ActionAuthorizer` iniettato prima di ogni esecuzione e mappa i risultati su `ToolReply` (`ask`, `done`, `failed`). `orchestrator/plugins.py` fornisce `AgentRegistry` per registrazione univoca, dispatch `ToolCall` e validazione del `ToolReply`. `main.py` continua a comporre lo stesso agent e gli stessi adapter concreti, esplicitamente.
- Test: regressione mirata A0-A3 **131 passed in 13.22s**, inclusi test di autorizzazione deny-by-default, mapping outcome, registry/dispatch, input invalido, isolamento import, computer action e wiring Live legacy. `compileall` completato.
- Esito: **PASS per il primo slice A3; milestone A3 parziale**. Plugin e registry sono testati ma non collegati al flusso conversazionale di produzione e non sono stati usati per azioni desktop live; la conferma UI e il callback locale di foreground/emergency-stop restano nel percorso legacy.
- Lint: Ruff mirato sui moduli A3 è PASS; per `tests/test_live_action_wiring.py` il controllo è passato escludendo l'`E731` preesistente non correlato. `git diff --check`, controllo whitespace ed esecuzione `compileall` sono PASS. Il tentativo di Pylance `checkSignatureCompatibility` è fallito per timeout dello strumento; i caller sono stati controllati con ricerca e test.
- Prossimo passo: completare Ruff sui file A3 senza modificare lint preesistente non correlato; poi decidere come introdurre una registry/dispatch con policy senza aggirare conferma UI, audit e stop di emergenza. Nessun commit creato.

## LOOP: A3.5 integrazione orchestrator/plugin e A3.6 Terminal

- Data: 2026-11-08
- A3.5: `ActionContext` immutabile include sessione, utente e metadata; `ActionAuthorizer.authorize` e plugin ricevono sia `ToolCall` completo (nome e argomenti) sia contesto. `ConversationOrchestrator` passa i tool declarations all'LLM, decodifica `FunctionCall` del contratto provider, dispatcha via `AgentRegistry`, serializza la risposta `ToolReply` (`done`/`ask`/`failed`) come messaggio tool e riprende la generazione. Limiti espliciti: una tool call per round e massimo di round configurabile; tool call senza registry, oltre il limite o multiple nello stesso round falliscono senza dispatch.
- Integrazione end-to-end Computer: fake LLM produce `computer_task`, il plugin usa ComputerAgent con `BrowserAutomation(MockBrowser)`, l'authorizer riceve call/context. Test separati provano allow (`done`, ricerca mock invocata), deny (`ask`, nessuna navigazione) e target visibile mancante (`failed`, nessun input); gli outcome serializzati arrivano al round LLM successivo. Nessun desktop reale/rete è stato usato.
- A3.6: aggiunti `TerminalExecutor` neutrale, `GuardedTerminalAdapter` sopra `core.terminal_agent` e `TerminalRunPlugin`. L'authorizer è invocato prima dell'esecuzione; deny→`ask`, richiesta override policy→`ask`, command rejection→`failed`, return code e output preservati con limite 4000 caratteri. Il test dell'adapter usa `TerminalAgent` con runner fake e DB temporaneo, verificando `shell=False`.
- E731: sostituita la lambda in `tests/test_live_action_wiring.py` con funzione nominata; Ruff passa sul file senza `--ignore`.
- Verifica combinata A0-A3.6: **143 passed in 11.60s**; `compileall` su `capabilities agents adapters orchestrator main.py`, Ruff selettivo su tutti i file coinvolti e `git diff --check` PASS. Rimane il warning preesistente pytest-asyncio sul fixture loop scope.
- Esito: **PASS per i contratti headless e i test di integrazione; runtime parziale**. Il nuovo path non è ancora cablato a Gemini Live/main/UI; l'autorizzatore è un'interfaccia injected, non ancora l'ActionPolicy/conferma/audit runtime.
- Prossimo gate: valutare la policy concreta e la composition root A4 separatamente; non collegare il plugin Terminal/Computer al Live finché la conferma di produzione, audit, foreground/emergency-stop e ciclo di vita non hanno adapter testati. Nessun commit creato.

## LOOP: A3.7 characterization composizione e sessione Live

- Data: 2026-11-08
- Ambito: test-only sul comportamento presente in `main.py`; nessun refactor runtime e nessun avvio di JARVIS.
- Evidenza codice: `_engine_mode()` legge il mode dal config e usa fallback Gemini su errore; `_resolve_engine_caps()` compone il provider LLM per pipeline, verifica campi/capability vision/audio e ricade su Gemini in caso di pipeline incompleta; `_open_session()` apre il client Gemini usando `v1alpha` o `v1beta`, oppure costruisce `PipelineEngine` dai slot LLM/STT/TTS, fa warmup e chiude nel `finally`.
- Nota: i metodi sotto test non sono pure functions: leggono config o usano `self.ui`/stato della sessione. A3.7 li caratterizza senza estrarre helper o alterare il runtime; l'estrazione in A4 dovrà introdurre funzioni pure solo se utile e preservare i risultati osservati.
- Test aggiunti in `tests/test_engine_composition_characterization.py`: fallback del mode, mode pipeline, capability/fallback, composizione pipeline da provider config fake, warmup e teardown, cleanup anche se il body sessione fallisce, e sessione Gemini con client async fake e versione API attesa. Il path tool legacy continua a essere caratterizzato da `tests/test_live_action_wiring.py` e `tests/test_provider_contracts.py` (terminal dispatch); A3 aveva già adattato il constructor ComputerAgent in `main.py`, non era corretto descrivere quel file come intatto.
- Verifica A3.7: selettiva **44 passed**; regressione combinata A0-A3.7 **150 passed in 12.64s**; `compileall`, Ruff senza `--ignore` sui file coinvolti e `git diff --check` PASS. Warning pytest-asyncio su fixture loop scope già noto.
- Esito: **PASS per characterization offline**, non prova connessione Live/rete, GUI, microfono o provider reali. Nessun cambiamento runtime in questo ciclo.
- Vincoli A4/A5 registrati: A4 estrae/compone soltanto e deve mantenere i characterization test verdi; non collega ancora il nuovo orchestratore al Live. L'authorizer di produzione e il flusso UI che presenta `ask`/raccoglie conferma non esistono ancora e devono essere progettati prima del wiring A5. Una tool call per round resta un limite noto da rivalutare in A5, dato il supporto Live a chiamate parallele.
- Nessun commit creato.
