# Report test manuali JARVIS

Data: 2026-11-08

## Ambito e limiti

- Percorso verificato: `C:\Users\PC\Downloads\jarvis-vii-app`.
- Il repository disponibile ha remote `ilfenomeno-gif/jarvis-new-era`; il task cita `jarvis-new-gen` e `Mark-LIV-main`, che non sono stati trovati nell'area di lavoro disponibile. I risultati si riferiscono quindi al codice locale `jarvis-vii-app`, non a una verifica del repository remoto citato.
- `config/api_keys.json` esiste ed e' popolato. Il valore della chiave non e' stato letto o riportato.
- L'utente non era disponibile a confermare le prove che avrebbero aperto una sessione Gemini, inviato testo a un servizio esterno o navigato sul web. Nessuna di queste azioni e' stata eseguita.
- Nessun file applicativo o dato del database e' stato modificato per i test; nessun commit o push e' stato eseguito.

## Risultati

| # | Test | Esito | Evidenza e note |
|---|------|-------|-----------------|
| 1 | Avvio e caricamento desktop | SKIPPED | `python main.py` non e' stato avviato: la configurazione API e' presente e l'avvio apre una sessione Gemini. La UI e il messaggio di ready non sono stati osservati. |
| 2 | Chat testuale | SKIPPED | Non e' stato inviato il prompt di prova: sarebbe trasmesso a Gemini e mancava l'autorizzazione richiesta dal task. Il database verificato non contiene messaggi di chat persistiti. |
| 3 | Plugin GEV e altri plugin | PASS (offline) | `python -m pytest -q tests/test_gev_plugin.py`: **9 passed**. Node e' installato (`C:\Program Files\nodejs\node.exe`). Il plugin non e' stato avviato nell'app; caricamento visivo e stato runtime restano non verificati. |
| 4 | Skill dichiarative | PASS (offline) | Trovati quattro file `skills/*/SKILL.md`; eseguiti i test di `tests/test_connectors_skills.py` nella suite mirata: suite combinata **44 passed**. Nessuna invocazione Live del tool `use_skill`. |
| 5 | Database SQLite | PASS (sola lettura) | `C:\Users\PC\AppData\Local\Jarvis VII\state\workflows.sqlite3`: `PRAGMA quick_check` restituisce `ok`. Tabelle workflow e memoria presenti. Non esistono tabelle `conversations`, `chat_sessions` o `chat_interactions`; `jarvis_memory` ha 0 righe e non contiene chiavi chat. |
| 6 | Azioni built-in e tool core | PASS (test offline); MANUAL SKIPPED | `tests/test_action_loader.py`, `tests/test_live_action_wiring.py` e gli altri test mirati relativi ai tool sono passati. Non sono stati lanciati programmi, azioni computer-control o ricerche web reali. |
| 7 | Routing e dispatch | PASS (test offline) | Eseguiti `tests/test_tool_router.py`, `tests/test_geo_router.py`, `tests/test_prompt_router.py`, `tests/test_action_loader.py` e i test di wiring: i gruppi sono passati (40 e 44 test rispettivamente). Il routing Live con Gemini non e' stato eseguito. |
| 8 | Log e memoria persistente | PASS (controllo limitato) | Nei file presenti `logs/gev.log` e `logs/local_3d_gen.log` la scansione non ha trovato le firme testuali `Traceback`, `CRITICAL` o `Unhandled exception`. SQLite e' integro (`quick_check=ok`), ma il contenitore `jarvis_memory` e' vuoto. La scansione non equivale a una revisione semantica completa dei log. |

## Verifiche automatiche offline

- `pytest -q tests/test_gev_plugin.py` — **9 passed**.
- `pytest -q tests/test_action_loader.py tests/test_tool_router.py tests/test_geo_router.py tests/test_prompt_router.py tests/test_plugin_sandbox.py` — **40 passed**.
- `pytest -q tests/test_connectors_skills.py tests/test_live_action_wiring.py tests/test_gev_mcp_client.py` — **44 passed**.
- `pytest -q tests/test_chat_orchestrator.py tests/test_memory_store_pool.py` — **12 passed**.

Questi test verificano contratti e comportamenti isolati; non sostituiscono il test visuale/manuale dell'app avviata.

## Anomalie, rischi e raccomandazioni

1. **Nessuna verifica end-to-end desktop/cloud:** avvio, chat Gemini, apertura GEV nell'interfaccia e query web restano da eseguire dopo esplicita autorizzazione.
2. **Percorso/repository non corrispondente:** verificare che `jarvis-vii-app` sia davvero la copia target di `Mark-LIV-main` richiesta; il remote locale e' `jarvis-new-era`, non `jarvis-new-gen`.
3. **Schema dati diverso dalla documentazione indicativa:** non sono presenti le tabelle chat citate nel task. Il codice disponibile persiste le sessioni `ChatOrchestrator` in `jarvis_memory`, che al momento e' vuota.
4. **Skill presenti nel codice:** la descrizione iniziale secondo cui le skill non sarebbero implementate non coincide con questa copia: sono presenti un `SkillRegistry`, l'azione `use_skill` e quattro cartelle skill.
5. **Azioni con effetti reali:** verificare `open_app`, `computer_control` e `web_search` nell'app solo in una sessione autorizzata, usando target innocui e confermando eventuali effetti prima dell'esecuzione.

## Esito complessivo

**PARZIALE — verifiche offline verdi; test manuali che richiedono rete/UI non eseguiti.** Non dichiarare l'app end-to-end verificata finche' non sono completati avvio e prove Live/UI nel target corretto.

## Confronto statico del percorso GEV nel runtime attivo

Verifica read-only sul checkout in esecuzione (`jarvis-vii-app`, remote `jarvis-new-era`, HEAD `677f153`), confrontato con `jarvis-new-gen` (`50fd4b7`). Nessun avvio dell'app/GEV e nessuna lettura dei log sono stati effettuati.

| Punto | `jarvis-new-era` @ `677f153` | Confronto con `jarvis-new-gen` @ `50fd4b7` |
|---|---|---|
| Config tool Live | `_build_config()` invoca `_select_tool_declarations()` sincronicamente; questo costruisce `_all_tool_declarations()` e chiama `PluginRegistry.get_tool_declarations()`. | Stesso percorso sincrono. |
| Attesa dichiarazioni GEV | Con GEV abilitato, `get_extra_tool_declarations()` attende `_startup_finished` con timeout `600 + 60 + 30 = 690 s`. | Stessa attesa e stesso timeout. Il rischio di sospendere l'event loop Live durante config/reconnect è trasferibile come ipotesi statica, non prova del freeze osservato. |
| Thread di avvio plugin | `main.py` avvia `start_all` in un thread daemon chiamato `gev-start`; `gev_plugin.start()` esegue `_start_runtime()` e segnala il completamento in `finally`. | Stesso avvio in thread dedicato: `npm ci` non viene eseguito direttamente dal thread GUI in questo percorso. |
| `save_screenshot` | La funzione è presente in `core/viewer3d.py`; `ui.py` la importa per il callback screenshot. | Nel target `jarvis-new-gen` controllato la funzione era assente, pur essendo importata dalla UI: questo difetto non si trasferisce al runtime attivo. |
| Installazione GEV | Se manca `node_modules`, esegue `npm ci` con `subprocess.run(..., timeout=600)`. | Stesso comando e timeout. L'esecuzione di installazione effettiva non è stata osservata. |

Il layer `providers/` di `new-era` non evita questo percorso: `_build_config()` usa comunque le dichiarazioni dei tool del plugin; `_resolve_engine_caps()` viene chiamato prima della costruzione della config ma non sostituisce la raccolta tool. Questa è una constatazione del flusso statico, non una riproduzione del problema audio.

### Stato remoto rispetto al runtime

- Branch locale: `fix/log-redaction`; non è configurato un upstream.
- `git fetch origin main` è riuscito. `origin/main`/`FETCH_HEAD` è `44e9336` (`Remove legacy HUD startup screen`); HEAD `677f153` è 10 commit avanti e `origin/main` non è avanti rispetto a HEAD.
- Non risultano quindi commit più recenti su `origin/main` da cui concludere che il freeze sia già stato corretto. Il fetch non ha modificato il worktree; i cambiamenti preesistenti sono stati preservati.

### Limiti e conclusione

La somiglianza statica trasferisce al runtime `new-era` il rischio dell'attesa sincrona fino a 690 s nell'event loop durante la costruzione della configurazione, condizionato all'abilitazione del plugin GEV. Non dimostra che questo sia il percorso attivo durante il freeze dopo la risposta vocale, né che la GUI sia bloccata. Lo stack già acquisito sul PID 20940 resta uno snapshot fuori dal blocco e non diagnostico. Per attribuire la causa serve acquisire lo stack del processo `new-era` durante il freeze.

## Test manuale chat UI — runtime `pythonw.exe`

- **Avvio:** `C:\Users\PC\Downloads\jarvis-vii-app\.venv\Scripts\pythonw.exe main.py`, PID `2520`, checkout `jarvis-new-era` @ `677f153`.
- **Chat HUD/Live:** inviato il prompt innocuo `Rispondi brevemente: chat pronta?`. Il testo è comparso nel pannello, ma non è stata osservata una risposta entro circa 60 secondi. Esito **FAIL/INCONCLUSIVO** per la risposta Live; non è stata acquisita evidenza che distingua mancata connessione, risposta tardiva o altro problema di runtime.
- **Pannello Gemini testuale:** inviati `Ciao, rispondi con una breve frase di conferma.` e, dopo il primo errore, `Rispondi solo con OK.`. Esiti remoti: `504 DEADLINE_EXCEEDED` e `503 UNAVAILABLE` (“This model is currently experiencing high demand”). Non è arrivata una risposta generata.
- **Recupero UI:** dopo ciascun errore la chat ha mostrato il messaggio, lo stato `Request failed; the conversation can continue.` e ha riabilitato input e pulsante `SEND`. L'app `pythonw.exe` è rimasta in esecuzione (PID 2520); l'interfaccia non si è bloccata.
- **Test automatizzati:** `python -m pytest -q tests/test_gemini_chat_headless.py tests/test_gemini_chat_ui.py tests/test_ui_input.py` — **26 passed**.
- **Diagnosi/fix:** gli errori del pannello dedicato sono risposte del servizio Gemini, non evidenza di eccezione applicativa non gestita. Non introdotti retry automatici né modifiche runtime: un retry aggiuntivo può aumentare latenza e chiamate e non risolve l'indisponibilità segnalata dal provider. `py-spy dump --pid 2520` non ha prodotto uno stack (`Failed to find python version from target process`), quindi la mancata risposta HUD/Live resta da diagnosticare.
- **Esito complessivo del test chat:** **PARZIALE/FAIL** — UI verificata come resiliente agli errori; nessuna risposta del provider ottenuta e percorso Live HUD non concluso.

## Fix chat e ripetizione del test

- **Causa applicativa identificata:** `core.gemini_chat` chiamava direttamente un solo modello (`gemini-3.8-flash`), bypassando la ladder condivisa. Una richiesta ha restituito 504 e una seconda 503. Il fallback storico FAST provava modelli 2.5 che, con questa configurazione, hanno restituito `404 NOT_FOUND` (“no longer available to new users”). La lista modelli dell'account espone modelli 3.x utilizzabili.
- **Modifiche:** aggiunta una ladder chat dedicata in `core.gemini` (Live, poi `gemini-3.8-flash`, `3.7-flash`, `3.6-flash`, `3.5-flash`); `gemini.call` ora può sollevare un errore aggregato esplicito quando richiesto, senza cambiare il comportamento dei chiamanti esistenti. Il pannello chat usa tale ladder e appiattisce la cronologia in un prompt testuale compatibile con il percorso Live. Il percorso Live distingue la chat dagli strumenti one-shot e applica una persona JARVIS conversazionale invece delle istruzioni da funzione di estrazione.
- **Verifica reale:** la nuova funzione chat ha risposto `Ciao.` in 3,34 s; dopo la correzione della persona ha risposto “Sono JARVIS, al tuo servizio per aiutarti con quello che ti serve.” in 7,13 s. Nell'app `pythonw.exe` riavviata (PID `504`) sono stati completati due turni: “Ciao JARVIS, chiamami Ada per questa conversazione.” → “Certamente, Ada...”; “Come mi hai appena chiamato?” → “Ti ho chiamata Ada...”. La cronologia è stata mantenuta tra i turni.
- **Test automatici finali:** `tests/test_gemini_chat_headless.py tests/test_gemini_chat_ui.py tests/test_ui_input.py` — **28 passed**. Include prova di fallback su un modello alternativo e di presentazione degli errori se tutti i modelli falliscono.
- **Stato:** test UI chat **PASS** dopo il fix. Questo non certifica il percorso vocale HUD/Live né esclude indisponibilità temporanee dei provider REST; questi test riguardano il pannello chat dedicato.

## Ripetizione test chat principale HUD/Live

- **Target:** chat principale HUD di `jarvis-new-era` @ `677f153`; non è stato aperto né usato il pannello Gemini dedicato o la conversazione di prova con Ada.
- **Avvio:** `.venv\Scripts\pythonw.exe main.py`, PID `26460`. Il server HUD ha risposto HTTP 200 su `127.0.0.1:8765`; il processo è rimasto attivo al termine.
- **Turni verificati nella chat HUD:** `Ciao JARVIS, rispondi con una sola frase: quanto fa 2 + 2?` → `Signore, il risultato di 2 + 2 è 4.`; `E quanto fa più 3? Rispondi solo col risultato.` → `7`; `Qual è la capitale d'Italia?` → `La capitale d'Italia è Roma.`.
- **Esito:** tre risposte osservate nell'interfaccia, incluso un follow-up contestuale; ciascuna è arrivata dopo pochi secondi. Il percorso Live HUD è quindi riuscito in questa ripetizione, e il precedente mancato riscontro non è stato riprodotto.
- **Log:** i messaggi sono arrivati da `source=hud_chat`; nessuna eccezione applicativa è stata osservata durante l'ultimo test. I log diagnostici temporanei creati per la prova sono stati rimossi.
- **Fix:** nessuna modifica runtime applicata: in questa ripetizione non è emerso un difetto riproducibile da correggere. Questo test verifica la chat testuale principale, non il riconoscimento vocale/audio; non modifica le conclusioni precedenti sulla chat Gemini dedicata.

## Riproduzione comando composto YouTube + GEV

- **Avvio diagnostico:** `.venv\Scripts\pythonw.exe -u main.py`, PID `24136`, checkout `jarvis-new-era` @ `677f153`. Output non bufferizzato in file temporanei locali per poter verificare le chiamate ai tool.
- **Comando inviato nella chat principale HUD:** `Apri YouTube e poi God Eye View`.
- **Evidenza di dispatch:** i log registrano in sequenza `[JARVIS] 📞 open_website` con esito `Opening the website inside Jarvis.`, quindi `[JARVIS] 📞 gev`, argomento `action: open`, con esito `Apro God's Eye View, signore.`.
- **Esito osservato:** JARVIS ha completato la risposta; la pagina locale God's Eye View è stata caricata; il processo `pythonw.exe` è rimasto attivo e l'HUD ha continuato a rispondere. Il freeze non si è riprodotto in questa prova testuale del dispatch multi-tool.
- **Limite diagnostico:** il testo è stato inserito nell'input HUD, non pronunciato al microfono. La prova verifica il dispatch Live `open_website` → `gev`, ma non riproduce il percorso di cattura vocale né dimostra che il precedente taglio audio sia risolto. Non essendosi verificato un freeze, non è stato possibile acquisire uno stack diagnostico durante il blocco.
- **Modifiche:** nessuna modifica runtime; i file di output diagnostico temporanei sono stati rimossi al termine della verifica.
