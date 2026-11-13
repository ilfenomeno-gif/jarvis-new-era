# IMPL-ARCH-001 — Migrazione incrementale alla piattaforma modulare

## Stato del documento

- **Ciclo:** F1-F4 progettazione; A0-A3.7 implementati e testati offline.
- **Stato del codice:** orchestratore headless collegato a registry e plugin Computer nel flusso tool-call; plugin Terminal validato come secondo adapter; composizione/session lifecycle Live e pipeline caratterizzati con fake. Il runtime Gemini Live non usa ancora il nuovo orchestratore.
- **Verdetto F4:** **GO CON MODIFICHE** — procedere solo per estrazioni incrementali, con adapter di compatibilità e gate di regressione. Una riscrittura simultanea di `main.py`, provider, agenti e UI è esclusa.
- **Target verificato:** checkout `jarvis-vii-app` / `jarvis-new-era`, branch `fix/log-redaction`, HEAD `677f153`.
- **Prerequisito operativo:** il worktree era già sporco prima di questi cicli; inoltre `main.py` è stato modificato in A3 solo per adattare l'iniezione obbligatoria di `ComputerAgent`. Prima di ogni refactor ulteriore, preservare le modifiche locali; nessuna estrazione o sostituzione del runtime è inclusa in A3.7.

## Prompt di lavoro per i cicli successivi

**Ruolo:** ingegnere software senior, neutrale e orientato a migrazioni verificabili.

**Task:** eseguire un solo milestone di questo piano per volta, riducendo l'accoppiamento dell'applicazione senza cambiare involontariamente il comportamento JARVIS.

**Contesto e vincoli:** Windows-first, Python `>=3.11`; mantenere Gemini Live e il realtime vocale sul desktop, UI/HUD/Iris, provider sostituibili, agenti specializzati, conferme, audit, redaction, sandbox e outcome espliciti. Estendere i contratti già esistenti; niente duplicazioni o nuove dipendenze senza necessità dimostrata.

**Formato di ogni ciclo:** diagnosi con prove nel repository → modifica atomica → test automatici → convalida funzionale, indicando `PASS`, `FAIL` o `DA VALIDARE LIVE` → recap in `LOOP_MEMORY.md`.

**Avvertenze:** distinguere codice presente da codice validato; non dichiarare headless una funzione che dipende ancora da GUI o hardware; non stampare segreti o transcript; non rimuovere l'adapter legacy finché tutti i consumer e i test non sono migrati.

**Valutazione:** a fine di ogni milestone confrontare i criteri di accettazione e aggiornare lo stato qui. Nessun commit, push o merge è implicito nel piano.

---

## 1. Obiettivo

Evolvere JARVIS da composizione di sottosistemi accoppiati a una piattaforma con:

1. un kernel piccolo che avvia, configura, collega e chiude i sottosistemi;
2. contratti espliciti per provider, strumenti, persistenza, workflow ed eventi;
3. un orchestratore testabile senza Qt, HTML, SQLite o servizi esterni;
4. agenti isolati con dipendenze iniettate;
5. UI desktop, HUD e server headless come client opzionali;
6. policy, conferme, audit, redaction e outcome applicati in modo uniforme.

La migrazione deve mantenere il runtime corrente durante tutto il percorso. Il codice legacy rimane adapter fino a quando il sostituto è stato testato e convalidato.

### Fuori ambito

- Riscrivere da zero Gemini Live, PyQt, HUD, Iris o gli agenti.
- Spostare il realtime vocale su un servizio remoto o rimuovere la modalità desktop.
- Migrare o cancellare in blocco database, file di memoria o configurazioni utente.
- Rendere n8n obbligatorio o introdurre un nuovo servizio cloud.
- Cambiare i guardrail, indebolire le conferme o eseguire azioni distruttive senza consenso esplicito.
- Rimuovere moduli legacy nello stesso ciclo in cui si introduce il nuovo contratto.

## 2. Diagnosi (F1 — stato verificato)

| Area | Evidenza attuale | Valutazione |
|---|---|---|
| Entry point / lifecycle | `main.py` contiene `main()` e la classe runtime; `Jarvis.run()` inizializza eventi asyncio, orchestrator task, HUD, UI e servizi. | **Accoppiamento presente**: `main.py` non è ancora un composition root sottile. |
| Provider | `providers/base.py` espone i protocolli `Engine`, `LLM`, `STT`, `TTS`; `providers/registry.py` scopre/builda provider. Il README documenta la pipeline e il fallback. | **Fondazione esistente**: consolidare, non creare una seconda API concorrente. Verificare nel codice effettivo dove risiede ciascuna decisione di fallback prima di spostarla. |
| Outcome | `core/outcome.py` fornisce helper `done`, `unverified`, `failed`, `ask`, `started` con rappresentazione testuale. | **Contratto esistente ma non coercitivo**: le funzioni non garantiscono ancora che ogni action/plugin lo usi. Migrazione compatibile necessaria. |
| Orchestrazione | La logica di sessione Live, routing e dispatch tool è in `main.py`; `core/chat_orchestrator.py` è un componente separato ma non il proprietario dell'intero ciclo conversazionale. | **Confine da estrarre** con test di caratterizzazione. |
| Agenti | `agents/computer_agent.py` ora dipende da porte neutrali in `capabilities/computer.py`; `agents/computer_plugin.py` espone un plugin con `ActionAuthorizer` obbligatorio; `orchestrator/plugins.py` fornisce dispatch tipizzato. Altri agenti continuano a usare implementazioni `core/`. | **Primo slice A3 isolato e dispatchabile**, ma non ancora collegato al flusso conversazionale di produzione; migrare gli altri agenti separatamente. |
| UI / headless | `ui.py`, `core/hud_bridge.py` e `core/jarvis_hud.html` realizzano UI/HUD; `server/app.py` è una FastAPI headless con una propria coda/task handler. | **Più superfici già disponibili**, ma non ancora client dello stesso orchestratore. |
| Persistenza / segreti | `core/memory_store.py` implementa SQLite; `memory/config_manager.py` gestisce configurazione; `core/secret_store.py` espone `SecretStore` e `SecretBackend`. `core/internal_workflow.py` gestisce workflow con archivio proprio. | **Implementazioni presenti, interfaccia comune assente o non dimostrata**. Non unificare i database senza inventario schema e piano di migrazione. |
| Guardrail | Sono presenti `core/guardrails.py`, `core/confirm.py`, `core/terminal_guard.py`, `core/harness/policy.py`, audit e sandbox. | **Controlli distribuiti**: definire un punto di enforcement comune e adattare le policy esistenti, senza bypass o rimozioni. |
| Workflow | `actions/n8n_bridge.py` e `core/n8n_outbox.py` collegano n8n; esistono anche workflow interni. | **Adapter esterno già separabile**: n8n non deve diventare dipendenza del kernel o dell'orchestratore. |
| Test | Esistono, tra gli altri, `tests/test_provider_contracts.py`, `tests/test_plugin_sandbox.py`, `tests/test_memory_store_pool.py`, `tests/test_n8n_bridge.py`, `tests/test_n8n_outbox.py`, `tests/test_server.py`, `tests/test_agent_loop.py`. | **Rete di regressione utile**; baseline e copertura dei confini vanno misurati prima di ogni migrazione. |

All'inizio della diagnosi il repository non conteneva package top-level `kernel/`, `capabilities/` o `orchestrator/`. In A1 sono stati creati `kernel/` e `capabilities/`; `orchestrator/` resta da creare in A2. Il worktree aveva modifiche locali in file applicativi, configurazioni, report e test: tali modifiche sono state preservate.

### Dipendenze e rischi principali

- Gemini Live ha semantica realtime e di sessione: un adapter deve preservare streaming, interrupt, tool call, riconnessione e modalità audio.
- Il dispatch degli strumenti è un confine di sicurezza: policy e conferme vanno applicate prima dell'esecuzione, non solo dichiarate nel prompt o nella UI.
- Il server headless e la UI hanno lifecycle e threading differenti; l'event bus deve definire ownership, ordinamento, errori e shutdown.
- La persistenza comprende più schemi e file privati. La migrazione deve essere additiva, reversibile e senza loggare dati personali.
- La suite include test Live e di integrazione: separare i test headless dai test che richiedono rete, API, audio o UI.
- **Sforzo indicativo:** progetto multi-sprint; stimare ogni milestone dopo la baseline, non trattare la riscrittura come una singola feature.

## 3. Architettura target e regole di dipendenza

```text
main.py
  └── kernel.bootstrap (composition root e lifecycle)
        ├── kernel (configurazione, event bus, logging, audit, policy)
        ├── orchestrator (turni, routing, memoria, outcome)
        │     ├── capabilities (contratti/porte stabili)
        │     ├── agents (plugin + dipendenze iniettate)
        │     └── adapters
        │           ├── providers/ (Gemini Live, LLM, STT, TTS)
        │           ├── persistence/ (MemoryStore e storage legacy)
        │           ├── workflows/ (interno, n8n)
        │           └── ui/ (PyQt, HUD, API headless)
        └── adapter legacy temporaneo (rimosso solo nell'ultimo gate)
```

### Regole vincolanti

1. `orchestrator/` dipende solo da contratti e tipi neutrali; non importa `ui`, Qt, HTML, `sqlite3`, SDK Gemini o client n8n.
2. I provider implementano i contratti `capabilities/`; non scelgono fallback, non leggono impostazioni globali e non orchestrano turni.
3. La selezione/fallback è responsabilità del composition root o dell'orchestratore, con policy esplicite e risultati osservabili.
4. Il kernel non conosce implementazioni UI, provider o workflow. Le dipendenze concrete sono assemblate in `kernel/bootstrap.py`.
5. Agenti e workflow non importano UI o storage concreti; ricevono porte/servizi nel proprio contesto. Per migrare gradualmente, gli adapter legacy sono ammessi temporaneamente.
6. Ogni azione con effetti esterni attraversa una policy comune, audit/redaction pertinenti e il flusso di conferma esistente.
7. Le nuove porte di persistenza non implicano un database unico: storage diversi possono implementare la stessa interfaccia, mantenendo proprietà e migrazioni proprie.
8. La UI desktop, HUD e FastAPI sono adapter opzionali dello stesso orchestratore. Nessun client possiede la logica conversazionale.
9. Le interfacce provider correnti in `providers/base.py` sono la fonte di compatibilità iniziale: nessun secondo set di protocolli duplicato.

## 4. Procedura (F2 — milestone, dipendenze e gate)

| ID | Milestone | File/package principali | Gate di uscita |
|---|---|---|---|
| A0 | Baseline e caratterizzazione | `tests/`, `docs/impl/`, report di baseline | Suite e scenari correnti registrati; worktree preesistente inventariato; latency baseline misurata o esplicitamente marcata non disponibile. |
| A1 | Contratti e kernel minimo | Da creare `kernel/`, `capabilities/`; adapter di `providers/base.py` | Contratti versionabili; event bus/config/lifecycle testabili senza UI; test dei provider esistenti passano invariati. |
| A2 | Composition root e orchestratore headless | Da creare `kernel/bootstrap.py`, `orchestrator/`; modifiche graduate a `main.py` | Conversazione testata con provider fake; avvio esistente delega al bootstrap; nessuna dipendenza GUI nel core orchestrator. |
| A3 | Policy, outcome e agenti | `kernel/action_policy.py` (da creare), `agents/`, adapter di `core/guardrails.py`, `core/confirm.py`, `core/outcome.py` | Test di contratto dimostrano deny-by-default dove richiesto, conferma, audit e outcome per gli strumenti migrati; agenti migrati ricevono dipendenze esplicite. |
| A4 | Porte di persistenza e workflow | Da creare porte persistence/workflow; adapter `core/memory_store.py`, `core/internal_workflow.py`, `actions/n8n_bridge.py`, `core/n8n_outbox.py` | Orchestrator usa solo porte; n8n disabilitato/non configurato non impedisce l'avvio; lettura e scrittura legacy conservano dati. |
| A5 | UI e server come client | `ui.py`, `core/hud_bridge.py`, `core/jarvis_hud.html`, `server/app.py`; adapter `ui/` (da creare) | UI desktop, HUD e server chiamano casi d'uso condivisi; orchestrator e test headless funzionano senza Qt. |
| A6 | Rimozione controllata degli adapter legacy | `main.py`, `core/`, `agents/`, test e documentazione effettivamente migrati | Nessun consumer legacy rilevato; suite completa e convalida live superate; rollback ancora disponibile fino alla release. |

**Dipendenze:** `A0 → A1 → A2`; `A3` dipende da A1 e si migra agente per agente; `A4` dipende da A1 e può procedere in parallelo ad A3; `A5` dipende da A2 e dai casi d'uso necessari in A3/A4; `A6` dipende da tutti i milestone richiesti dal runtime distribuito.

### Sotto-passi atomici e test

#### A0 — Baseline (primo ciclo di implementazione)

1. Salvare `git status --short` e inventariare le modifiche preesistenti; non ripulire il worktree con operazioni distruttive.
2. Eseguire i test di confine già presenti:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q tests\test_provider_contracts.py tests\test_plugin_sandbox.py tests\test_memory_store_pool.py tests\test_n8n_bridge.py tests\test_n8n_outbox.py tests\test_server.py tests\test_agent_loop.py
   ```
3. Registrare separatamente test falliti prima delle modifiche, test Live non eseguibili e dipendenze mancanti.
4. Misurare su almeno 30 turni sintetici locali i tempi p50/p95 di dispatch e il tempo al primo output audio con la stessa configurazione. Se non è possibile una misurazione attendibile, segnare il gate latency `DA VALIDARE`, senza inventare baseline.
5. Eseguire e documentare i flussi di caratterizzazione: avvio desktop; turni vocali Gemini Live e interrupt; chat testuale; tool con conferma; workflow n8n mockato; avvio FastAPI headless.

#### A1 — Contratti e kernel minimo

1. Definire in `capabilities/` i tipi neutrali per eventi di conversazione, tool request/result, provider e persistenza. Riutilizzare i protocolli `Engine`, `LLM`, `STT`, `TTS` esistenti; se occorre spostarli, mantenere import di compatibilità in `providers/base.py`.
2. Definire lifecycle `start/close`, errori espliciti e un event bus interno con subscription/unsubscription e shutdown deterministico. Non introdurre callback globali mutabili.
3. Aggiungere configurazione tipizzata con validazione e adapter verso i valori attuali di `memory/config_manager.py` e `config/api_keys.json`; segreti fuori dalla configurazione serializzata e dai log.
4. Testare pub/sub, cancellazione, error propagation, lifecycle idempotente e validazione config senza rete o Qt.

#### A2 — Bootstrap e orchestratore

1. Aggiungere un composition root che costruisca provider, store, policy, agenti e UI attraverso factory iniettate.
2. Estrarre prima un singolo caso d'uso testabile (turno di chat testuale con provider fake) senza cambiare il percorso audio Live.
3. Spostare successivamente gestione sessione e tool dispatch dietro un protocollo `ConversationEngine`; l'adapter Gemini Live mantiene le API e il comportamento attuali.
4. Ridurre `main.py` a parsing CLI, bootstrap, gestione del codice d'uscita e cleanup; estrarre una sola responsabilità per commit/logica di ciclo.
5. Prima di A4, conservare characterization test per `_engine_mode`, `_resolve_engine_caps`, composition di LLM/STT/TTS e lifecycle di `_open_session` sia Live sia pipeline. In A4 estrarre/comporre senza collegare ancora l'orchestratore headless al runtime Live.
6. Testare orchestratore con provider fake e verificare che importare il package headless non importi PyQt, WebEngine o SDK cloud.

#### A3 — Policy e agenti

1. Definire un `ActionPolicy` con decisione esplicita, motivazione, classe di rischio e necessità di conferma; collegarlo a conferma/audit già esistenti.
2. Integrare inizialmente gli handler correnti con adapter, senza cambiare la semantica delle azioni non migrate.
3. Migrare ogni agente separatamente: dichiarazione delle capability richieste, `ActionContext` iniettato e test unitari con mock. A3.5 richiede un test headless orchestrator→registry→plugin con esiti allow/deny; A3.6 richiede un secondo plugin per validare la generalità del contratto prima di A4.
4. Conservare plugin sandboxati in processo separato con IPC JSON; nessun provider non fidato deve ricevere oggetti UI o segreti in chiaro.
5. Rendere obbligatorio l'outcome per i nuovi handler; per quelli legacy aggiungere conversione al confine e migrare a piccoli gruppi. Mantenere compatibili schema e istruzioni di `core/outcome.py` fino alla migrazione di tutti i consumer.

#### A4 — Persistenza e workflow

1. Definire porte minime per memoria conversazionale e stato, senza esporre query o connessioni SQLite all'orchestratore/agenti.
2. Avvolgere `MemoryStore` e gli archivi workflow con adapter separati; testare ciascuno contro il contratto con database temporanei.
3. Definire `WorkflowEngine`; implementazioni iniziali: adapter workflow interno e adapter n8n. Errori remoti diventano outcome espliciti, mai successi simulati.
4. Usare `SecretStore`/`SecretBackend` come confine segreti; non introdurre fallback in chiaro.
5. Nessuna migrazione distruttiva: schema versionato, backup e test di lettura dei dati creati dalla versione precedente.

#### A5 — UI e server

1. Esporre dall'orchestratore comandi/eventi indipendenti dalla UI.
2. Adattare prima la UI PyQt attuale; poi il bridge HUD locale; infine `server/app.py`, mantenendo distinti authentication, lifecycle e trasporto.
3. Definire timeout, backpressure, disconnessione e cleanup per eventi UI/server. Il server headless non deve avviare componenti desktop o microfono.
4. Testare l'orchestratore senza installare/inizializzare Qt; testare bridge e API con client finti e lifecycle FastAPI.

#### A6 — Deprecazione e rimozione

1. Cercare consumer, import, entry point e plugin che dipendono dall'interfaccia legacy.
2. Emettere deprecation solo dove non espone dati sensibili o rompe i plugin supportati.
3. Rimuovere un adapter alla volta, solo dopo zero consumer e test equivalenti.
4. Conservare l'adapter precedente o un rollback applicabile per almeno una release; rimuovere solo dopo convalida di runtime e aggiornamento documentazione.

## 5. Modifiche per file (previsione)

| Percorso | Stato previsto | Responsabilità |
|---|---|---|
| `docs/impl/IMPL-ARCH-001-piattaforma-modulare.md` | Creato in F3 | Contratto del programma di migrazione, gate e verifiche. |
| `docs/impl/ROADMAP.md` | Riferimento da aggiungere | Indice del track architetturale; non sostituisce le meccaniche già elencate. |
| `kernel/` | Creato in A1 (primitivi iniziali) | `Kernel` lifecycle async, event bus, stato e config pubblica tipizzata; bootstrap e policy restano da creare. |
| `capabilities/` | Creato in A1/A3 | `ToolCall`, `ToolReply`, porte computer/terminal e re-export identici dei protocolli provider esistenti. |
| `orchestrator/` | Creato in A2/A3.5 | Conversazione headless con LLM iniettato e `AgentRegistry`; dispatch tool bounded a una call per round, senza wiring di produzione. |
| `agents/` | Migrazione graduale, A3/A3.6 | Computer e Terminal ricevono capability, `ActionContext` e authorizer iniettati; altri agenti restano legacy. |
| `adapters/terminal.py` | Creato in A3.6 | Traduce gli errori/results di `core.terminal_agent` nel contratto capability mantenendo la policy legacy. |
| `providers/` | Adattamento graduale, A1-A2 | Provider implementano protocolli; fallback e composizione fuori dalle implementazioni. |
| `core/outcome.py` | Adapter/migrazione, A3 | Conservare il formato compatibile al confine e imporre esiti espliciti ai nuovi handler. |
| `core/secret_store.py`, `core/memory_store.py`, `core/internal_workflow.py` | Adapter, A4 | Implementare porte senza cambiare formato dati o cifratura. |
| `actions/n8n_bridge.py`, `core/n8n_outbox.py` | Adapter, A4 | Workflow n8n opzionale dietro `WorkflowEngine`. |
| `ui.py`, `core/hud_bridge.py`, `core/jarvis_hud.html`, `server/app.py` | Adapter, A5 | Client dell'orchestratore; niente logica di routing provider duplicata. |
| `main.py` | Adattamento minimo A3; extraction-only A4 | A3 aggiorna il costruttore ComputerAgent per capability esplicite; A3.7 ne caratterizza composizione e sessioni. Nessun wiring Live al nuovo orchestratore in A4. |
| `tests/` | Esteso in ogni milestone | Test di contratto, orchestratore, agenti e adapter. |

## 6. Piano test e criteri di accettazione

### Test automatici

Baseline iniziale:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_provider_contracts.py tests\test_plugin_sandbox.py tests\test_memory_store_pool.py tests\test_n8n_bridge.py tests\test_n8n_outbox.py tests\test_server.py tests\test_agent_loop.py
```

Per ogni milestone:

```powershell
.\.venv\Scripts\python.exe -m compileall kernel capabilities orchestrator providers agents core server
.\.venv\Scripts\python.exe -m pytest -q
```

Il comando `compileall` sui package nuovi va aggiornato fino a quando `kernel/`, `capabilities/` e `orchestrator/` non esistono. Test che dipendono da rete, provider reali, GUI o hardware vanno selezionati/segnalati separatamente, non convertiti in mock senza dichiararlo.

### Criteri osservabili

| ID | Criterio | Evidenza richiesta |
|---|---|---|
| AC-1 | I flussi legacy di avvio, chat, tool, conferma e workflow non regrediscono. | Suite baseline prima/dopo e report dei test Live separati. |
| AC-2 | L'orchestratore lavora con provider fake senza Qt, browser, API keys o rete. | Test isolati e verifica import/dependency graph. |
| AC-3 | Gemini Live desktop continua a inviare/ricevere audio in streaming, gestire interrupt e tool response. | Test di contratto e prova manuale live con log non sensibili. |
| AC-4 | Fallback e retry sono centralizzati e limitati; nessun retry duplica tool mutanti o output già emesso. | Test deterministici di selezione, timeout, retry e idempotenza. |
| AC-5 | Ogni azione migrata passa dalla policy; le azioni irreversibili mantengono conferma e audit. | Test deny/allow/ask, audit redatto e test di regressione guardrail. |
| AC-6 | `done`, `unverified`, `failed`, `ask`, `started` non vengono trasformati in falsi successi. | Test di serializzazione/compatibilità e test d'integrazione con tool handler. |
| AC-7 | n8n non è necessario all'avvio o alla chat di base. | Avvio e test con adapter n8n assente/disconnesso; errore esplicito per la sola funzione n8n. |
| AC-8 | La memoria legacy resta leggibile e non vengono persi record durante upgrade/rollback. | Test su fixture versione precedente e database temporaneo; nessuna modifica alla memoria utente durante i test. |
| AC-9 | Desktop UI, HUD e server headless sono client separati dello stesso caso d'uso; il core parte headless. | Test API/UI adapter con mock e test import headless. |
| AC-10 | Il refactor non peggiora sensibilmente la reattività. | Confronto sulla stessa macchina/config: p95 dispatch e primo output non oltre il 10% sopra la baseline; se la baseline non è attendibile, criterio `DA VALIDARE LIVE`, nessun claim PASS. |

### Convalida manuale obbligatoria

| Scenario | Prompt/azione | Risultato atteso |
|---|---|---|
| Realtime desktop | Parlare con JARVIS, interromperlo durante una risposta, poi riprendere. | Audio e interrupt continuano sul desktop; nessuna doppia risposta/tool call. |
| Tool con conferma | Richiedere un'azione distruttiva innocua da test o simulata. | Nessun effetto prima della conferma; annullamento e conferma producono esiti distinti e audit redatto. |
| HUD | Inviare un messaggio e osservare stato/risposta. | Il client riceve eventi senza invocare direttamente provider o storage. |
| Headless | Avviare il server senza desktop e inviare un task di test. | Health/task API funzionano senza PyQt, microfono o browser. |
| n8n offline | Lasciare l'adapter non configurato e chiedere un task non n8n. | JARVIS continua a operare; il task n8n restituisce errore esplicito se richiesto. |
| Upgrade memoria | Aprire fixture del formato precedente e leggere/scrivere su DB temporaneo. | Record preservati e nessuna modifica alla memoria reale dell'utente. |

## 7. Criteri di accettazione (checklist PASS/FAIL)

- [ ] Il comportamento corrente è caratterizzato prima del refactor.
- [ ] Nessun nuovo package reimplementa un contratto già presente senza piano di compatibilità.
- [ ] I provider sono sostituibili attraverso contratti e non decidono autonomamente il fallback.
- [ ] L'orchestratore è importabile e testabile senza UI o servizi esterni.
- [ ] Le azioni e gli agenti migrati applicano policy, conferma, audit e outcome.
- [ ] Persistenza e segreti restano compatibili e non sono esposti nei log.
- [ ] Gemini Live, HUD/Iris, agenti specializzati e modalità headless restano supportati.
- [ ] Test mirati, test completi e prove live sono riportati separatamente con output reale.
- [ ] Il rollback è verificabile per ogni milestone.
- [ ] Gli adapter legacy vengono rimossi solo dopo la prova di zero consumer.

## 8. Fattibilità (F4)

### Checklist

- [x] I principali punti di innesto citati esistono: `main.py`, `providers/base.py`, `providers/registry.py`, `core/outcome.py`, `agents/`, `server/app.py`, store, sandbox e adapter n8n.
- [x] I package `kernel/`, `capabilities/`, `orchestrator/` sono dichiarati esplicitamente come **da creare**.
- [x] Non sono richieste nuove dipendenze per i primi contratti/test.
- [x] Ogni milestone ha test e criteri misurabili o un'etichetta `DA VALIDARE LIVE`.
- [x] Il piano preserva conferme, audit, redaction e sandbox.
- [x] Il piano evita migrazioni distruttive e mantiene adapter di rollback.
- [ ] Baseline automatica e prestazionale eseguita: **da fare in A0**.
- [ ] Convalida live dei flussi vocali, UI e provider reali: **da fare nei gate pertinenti**.
- [ ] Worktree isolato/branch di implementazione pronto: **da fare prima di F5**, dato il worktree locale già modificato.

### Verdetto

**GO CON MODIFICHE** per iniziare da A0 e poi A1 con contratti/adapters. **NO-GO** per una riscrittura big-bang o per rimozioni del legacy prima dei gate A6. Nessun codice applicativo è stato cambiato da questo documento.

## 9. Rollback

1. Ogni milestone si implementa in commit piccoli su branch dedicato, dopo aver preservato e separato le modifiche preesistenti.
2. Il bootstrap deve poter selezionare l'adapter legacy fino alla convalida completa del nuovo percorso.
3. Le modifiche a schema dati sono additive e versionate; prima di una migrazione reale si prepara backup e prova di restore.
4. In caso di regressione, disattivare il nuovo adapter tramite configurazione/factory e tornare al percorso precedente senza cambiare formato dei dati.
5. Non usare `git reset --hard`, `git checkout` distruttivi o cancellazioni dei file utente come procedura di rollback.
6. Rimuovere il percorso legacy solo in A6, quando AC-1…AC-10 sono soddisfatti e la release precedente resta ripristinabile.

## 10. Registro di implementazione

| Fase | Stato | Evidenza |
|---|---|---|
| F1 — Diagnosi | **Completata** | Struttura reale e contratti ispezionati nel checkout `677f153`; worktree preesistente registrato e preservato. |
| F2 — Procedura | **Completata** | Milestone A0-A6, dipendenze, test, gate e rollback definiti. |
| F3 — File implementativo | **Completata** | Specifica architetturale creata e collegata alla roadmap. |
| F4 — Fattibilità | **GO CON MODIFICHE** | Migrazione incrementale; non autorizza il big-bang. |
| A0 — Baseline automatica | **PASS mirato** | Suite confini prima delle modifiche A1: **80 passed in 11.43s**. La suite combinata dopo A1: **90 passed in 8.23s**. Esecuzioni con Python 3.13.7; pytest-asyncio emette un warning di configurazione preesistente. |
| A0 — Baseline live/latency | **DA VALIDARE LIVE** | In questo ciclo non sono state misurate 30 sessioni né provati microfono, interrupt e primo chunk audio; non dichiarare una baseline prestazionale. |
| A1 — Implementazione | **PASS per le primitive iniziali** | Creati `kernel/` e `capabilities/`; il wiring legacy delle capability Computer resta nel composition code esistente. |
| A2 — Use case headless | **PASS per il primo slice** | Conversazione con LLM fake, streaming, cronologia, eventi, serializzazione concorrente e import senza Qt/SDK cloud: coperta da `tests/test_headless_conversation.py`; bootstrap e wiring di produzione ancora mancanti. |
| A3.5 — Conversation/plugin integration | **PASS headless** | Il tool-call LLM è dispatchato tramite `AgentRegistry` al plugin Computer; allow/deny, `ActionContext`, serializzazione `done`/`ask`/`failed` e tool result verificati con backend browser mock in `tests/test_orchestrator_agent_integration.py`. Una call per round; limite round configurabile. |
| A3.6 — Second plugin | **PASS headless** | `TerminalRunPlugin` usa `TerminalExecutor`; `GuardedTerminalAdapter` riutilizza `TerminalAgent` e `TerminalGuard`. Test di deny, policy override→ask, blocked→failed, exit code/output e adapter in `tests/test_terminal_plugin.py`. |
| A3 — Stato complessivo | **PASS per i contratti headless; runtime parziale** | Computer e Terminal verificano il contratto plugin; il runtime/main non li registra né usa l'orchestratore headless. Altri agenti e `ActionPolicy` di produzione restano da migrare. |
| A3.7 — Live characterization | **PASS offline** | Nuovi test caratterizzano fallback/mode e risoluzione capability, composizione LLM/STT/TTS da config finta, apertura/chiusura Live con client finto e pipeline warmup/cleanup, incluso errore nel corpo sessione. I metodi in `main.py` non sono pure functions: i test ne congelano il comportamento con config/UI/provider mock. Dispatch legacy Computer/Terminal è inoltre coperto da `tests/test_live_action_wiring.py`. Nessuna rete/API o GUI reale. |
| A4 — Composition root | **NON INIZIATO** | Gate: mantenere verdi i characterization A3.7; estrarre soltanto il wiring esistente, senza sostituire Live con `ConversationOrchestrator`. Flusso di conferma umana del nuovo `ActionAuthorizer` rimane prerequisito esplicito prima del wiring A5. |
| F5 — Implementazione codice | **Parziale** | A1-A3.7 implementati; nessuna composition root estratta e nessun wiring del nuovo orchestratore al runtime Gemini Live/UI. `main.py` contiene il solo adattamento A3 al constructor ComputerAgent. |
| F6 — Verifica | **PASS mirato** | Regressione combinata A0-A3.7: **150 passed in 12.64s**; `compileall`, Ruff sui file coinvolti e `git diff --check` passati. Nessun `--ignore E731`; la lambda del test wiring è stata sostituita. Warning pytest-asyncio preesistente invariato. |
| F7 — Convalida | **PASS headless / DA VALIDARE LIVE** | Fake client/provider verificano i confini di sessione e composizione; i plugin usano backend/runner fake. Nessuna API, GUI, microfono, azione desktop o comando OS reale eseguiti. |
| F8 — Recap | **Parziale** | A3.7 chiuso come characterization offline. Prossimo gate A4: estrazione composition-only preservando i test, senza replacement Live; progettare separatamente il flusso di conferma utente prima di A5. |

## 11. Recap del ciclo

Il piano traduce l'obiettivo “un cervello orchestratore, interfacce esplicite, provider sostituibili, UI opzionale” in una migrazione A0-A6 con dipendenze, criteri osservabili e rollback. A0 ha ottenuto una baseline automatica mirata di 80 test; A1 primitive isolabili; A2 conversazione headless; A3.5 ha collegato conversazione, registry e Computer plugin nei test; A3.6 ha validato il contratto anche con Terminal e l'adapter alla guardia legacy; A3.7 ha congelato il comportamento corrente di composizione/mode/sessione con fake. La regressione mirata combinata A0-A3.7 ha **150 test passati**. `main.py` era già stato toccato in A3 per il constructor injection; non è stato ulteriormente refactorizzato in A3.7. Il runtime Gemini Live/UI non usa ancora il nuovo dispatch e il flusso di conferma umana per il nuovo authorizer è assente: questi restano vincoli prima del wiring A5.
