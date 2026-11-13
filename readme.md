# JARVIS VII

Assistente desktop AI personale (Windows-first), fusione di:

- **B** — [`ilfenomeno-gif/jarvis-new-gen`](https://github.com/ilfenomeno-gif/jarvis-new-gen) (`Mark-LIV-main`, baseline `origin/main` @ `41e405e`): app desktop PyQt6 + Gemini Live, sicurezza (guardrail, DPAPI, audit, conferme UI), plugin, multi-agente, GEV, 3D, ~55 file di test.
- **C** — [`FatihMakes/Mark-LVI`](https://github.com/FatihMakes/Mark-LVI) (@ `4d4035c`): layer `providers/` (motore STT+LLM+TTS intercambiabile con fallback a Gemini Live), protocollo `outcome` (done/unverified/failed), dashboard HTTPS+AES-GCM, avatar olografico.
- **A** — n8n Cloud come **motore di workflow** via webhook (canale solo outbound; eventi n8n→desktop via polling "outbox").

**Architettura**: Opzione 2 — *Python come cervello, n8n come motore di workflow*. Il realtime vocale resta sul desktop; n8n orchestra flussi/integrazioni/schedulazioni come tool remoto.

## 🌟 Nuove Funzionalità

- **Simbiosi Hardware**: monitora CPU, RAM e processi tramite il
  `SymbiosisHub`; include anche moduli per rete, appunti e monitor. I moduli
  dipendono dalla disponibilità delle rispettive funzionalità sul sistema.
- **Logging Diagnostico**: log strutturati, filtro dei dati sensibili e
  limitazione dei messaggi ripetuti. I quattro file principali sono
  `logs/jarvis.log`, `logs/jarvis.diagnostics.log`,
  `logs/jarvis.session.jsonl` e `logs/jarvis.external.log`.
- **Plugin Web e interfacce HTML/JS**: l'HUD usa contenuti web e i plugin
  Python possono aprire servizi nel browser integrato, come code-server.
  Il caricatore attuale scopre plugin `.py`: non risulta un caricatore
  dedicato per plugin HTML/JS autonomi.

## 🚀 Installazione e Avvio

Su Windows 10/11, con Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install
.\.venv\Scripts\python.exe main.py
```

In alternativa, dopo aver creato `.venv`, avvia con `python main.py`;
`python main.py --check-startup` verifica interprete e dipendenze iniziali.
Il motore vocale predefinito richiede una chiave Gemini, configurabile
all'avvio. Per i prerequisiti e le opzioni locali, consulta
[INSTALL_WINDOWS.md](INSTALL_WINDOWS.md).

## 🧩 Architettura

`core/` contiene runtime, orchestrazione, HUD, simbiosi e logging;
`actions/` espone le azioni richiamabili; `plugins/` raccoglie estensioni
Python rilevate dal caricatore; `docs/` contiene guide e dettagli tecnici.
L'interfaccia desktop usa PyQt e integra una HUD web.

## 📚 Documentazione Dettagliata

- [Sistema di Logging Diagnostico](docs/ARCHITETTURA.md): formato, file,
  filtri, report e modalità legacy.
- [Plugin Web](docs/PLUGIN_WEB.md): documento richiesto, **non ancora presente**
  nel progetto.
- [Connettori e Simbiosi Hardware](docs/CONNETTORI.md).

## 🛠️ Comandi Rapidi

| Comando vocale | Funzione |
|---|---|
| «Jarvis, dammi il report del sistema» | Genera e salva il report diagnostico. |
| «Jarvis, che errori ci sono?» | Richiede il report diagnostico. |
| «Jarvis, controlla la CPU» | Mostra l'utilizzo della CPU. |
| «Jarvis, controlla la RAM» | Mostra l'utilizzo della memoria. |
| «Jarvis, quali processi usano più CPU?» | Elenca i processi con maggiore utilizzo CPU. |
| «Jarvis, leggi gli errori di Chromium» | Legge il log Chromium, se acquisito esternamente. |

Il comando «Jarvis, apri il tornado» non risulta associato a un plugin
dedicato nella versione attuale.

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

Su Windows l'uscita vocale prova WASAPI, DirectSound e infine MME, privilegiando
il dispositivo predefinito di Windows o quello scelto nelle impostazioni.
WASAPI usa la conversione del mixer in modalità condivisa per i sample rate
non nativi. Ogni dispositivo viene provato con silenzio prima dell'uso:
un'apertura riuscita non garantisce che l'audio si muova realmente. Se necessario,
`JARVIS_AUDIO_HOST_API_ORDER=directsound,mme,wasapi` cambia esplicitamente
l'ordine; l'ingresso mantiene la propria selezione. Se nessun dispositivo passa
la prova, verifica il dispositivo predefinito e le impostazioni audio di Windows.

### Identità e wake word

L'assistente è Jarvis quando la mappa è attiva. Diventa Iris solo quando
l'avatar è mostrato, tramite «Iris rivelati» o la funzione HUD `reveal`;
«Iris nasconditi» e il ritorno alla mappa ripristinano Jarvis. Nome, prompt
e voce seguono la modalità visualizzata, non la wake word.

Con la wake word abilitata, il modello predefinito `hey_jarvis` apre il
microfono. Facoltativamente, `JARVIS_IRIS_WAKE_WORD_MODEL` può indicare il
percorso di un modello openWakeWord ONNX Iris locale: anche questa frase apre
solo il microfono, senza cambiare modalità. Il modello Iris non è incluso né
scaricato automaticamente. I modelli devono essere distinti; se quello Iris
non si carica, Jarvis resta disponibile quando il suo modello funziona.

Un esempio disponibile è il modello
["Hey Iris"](https://openwakeword.com/library/2502), che richiede accesso al
sito per il download ed è concesso per uso personale e non commerciale alle
condizioni indicate dal fornitore. Riconosce la frase «Hey Iris», non è stato
verificato con «Iris» da solo e non è stato collaudato con questa applicazione.

Il cambio di modalità ricrea la sessione Live senza riprendere la conversazione
precedente, perché prompt e voce vengono fissati alla connessione; l'audio
pronunciato durante la riconnessione può andare perso. Le risposte sono generate
dal modello e l'aderenza all'identità non è deterministica.

### Chat e riepilogo

Le risposte articolate possono usare elenchi e grassetto nelle chat HUD, GEV
e Gemini. Nella chat Gemini il Markdown viene applicato al termine dello
streaming. Il testo inviato alla lettura viene ripulito dai simboli Markdown
e i passaggi tra righe vengono separati con punteggiatura; la voce
Live è generata direttamente dal modello e segue un'istruzione equivalente.
Chiedi «organizza la conversazione» o «riassumi cosa abbiamo detto» per
riassumere gli ultimi 20 messaggi della sessione (fino a 40 su richiesta).
Il riassunto usa il modello selezionato: con Gemini la cronologia selezionata
viene inviata al servizio cloud; con il cervello locale viene usato Ollama.
Non include messaggi delle sessioni precedenti non presenti nella cronologia
corrente.

### Appunti e note

Chiedi «prendi appunto che devo comprare il latte» o «salva una nota»;
senza categoria viene usata **Generale**. «Mostrami gli appunti» li elenca
con categoria, data e ID; è anche possibile cercarli per testo. Per
«staccare» una singola nota serve il suo ID, oppure si può esportare
un'intera categoria: viene creato un nuovo file `.txt` sul Desktop senza
sovrascrivere file esistenti. La cancellazione riguarda un solo ID e richiede
conferma esplicita.

Le note sono salvate localmente in `config/notes.json`, escluso da Git.
Il precedente plugin `quick_notes` usa un archivio separato: le sue note non
sono migrate automaticamente. Il Desktop deve essere disponibile nel percorso
`~/Desktop`.

### Task programmati e briefing

Chiedi, ad esempio, «tra 10 minuti ricordami di bere», «ogni mattina alle 8
dimmi il meteo» oppure «prepara il briefing mattutino». I task di tipo
promemoria, meteo e briefing sono salvati in `config/scheduled_tasks.json`,
usano l'ora locale e vengono ricaricati all'avvio. Jarvis deve essere in
esecuzione per consegnarli: quelli scaduti vengono elaborati al successivo
avvio. Non sono supportati comandi terminale arbitrari programmati.

Il briefing usa la città memorizzata o indicata nella richiesta, la ricerca web
per meteo e notizie, e i task Jarvis di oggi; il calendario esterno non è
integrato. Se la voce non è connessa, il risultato programmato appare nella UI.
Per sicurezza l'apertura app richiede conferma, come il terminale: `ipconfig`
e `ipconfig /all` sono consentiti dalla policy; opzioni come `/release` e
`/renew` restano bloccate. È consentito anche `ping` seguito da un solo host,
senza opzioni. Dopo la conferma il comando viene eseguito in background: la
coda può proseguire e il risultato completo compare nella UI, mentre la
lettura vocale usa al massimo tre righe e 300 caratteri. Se la voce non è
connessa o resta occupata, la mancata lettura viene segnalata nella UI.
La ricerca delle app include PATH, Program Files e AppData Local; percorsi
bloccati, nomi ambigui e altre restrizioni di sicurezza restano esclusi.
Per richiedere esplicitamente l'apertura tramite terminale, dire ad esempio
«apri notepad tramite terminale»: occorre confermare il comando mostrato.
Sono consentiti soltanto `start notepad`, `start calc`, `start chrome`,
`start mspaint` e `start explorer`, senza argomenti o operatori shell.
L'avvio viene richiesto in background e non verifica che la finestra si apra.

Il comando «cosa vedi» mostra subito l'avvio dell'analisi dello schermo nel
log della UI. Se l'analisi supera i 20 secondi, compare un avviso: l'operazione
continua e la risposta viene mostrata quando è pronta.
Vision richiede fino a 2000 token e usa il livello di ragionamento `low` per
Gemini 3.8; Gemma non riceve impostazioni di thinking. Se non c'è testo finale,
l'ultimo `thought` non vuoto viene mostrato e letto come ripiego: può essere
incompleto o inesatto e non equivale a una risposta finale verificata. I
`thought` non vengono stampati nel terminale; la risposta finale può comunque
contenere informazioni private dello schermo.
In caso di errore 503, Vision riprova il modello principale tre volte con
attese di 1 e 2 secondi, quindi dopo 4 secondi prova `gemma-4-26b-a4b-it`.
In caso di errore 429 prova immediatamente lo stesso fallback, con immagine e
richiesta identiche. Lo screenshot inviato è largo al massimo 1024 pixel;
il timeout HTTP è di 20 secondi per il modello principale e di 45 secondi per
il fallback. La riduzione può compromettere la leggibilità dei testi piccoli.
Tra analisi consecutive è previsto un intervallo di 10 secondi dalla fine
dell'ultima richiesta; anche una richiesta già in corso blocca ulteriori
analisi. Dopo due risposte consecutive con errore interno 500, le richieste
successive usano al massimo 800 pixel di larghezza, fino al primo risultato
diverso da 500, quando torna il limite di 1024 pixel. Le impostazioni valgono
per la sessione corrente e si azzerano al riavvio.
La disponibilità del modello e i limiti di quota dipendono dal progetto e
dal servizio API: non è garantita una quota gratuita separata o più alta.
Per limitare l'analisi alla finestra in primo piano, richiedi esplicitamente
«analizza la finestra attiva»: la modalità `active_window` cattura la sua area
visibile sul desktop, anche se parzialmente fuori schermo. Altre finestre che
la coprono possono comparire nella cattura; se non è disponibile una finestra
valida, viene segnalato un errore invece di inviare l'intero schermo.
Se anche il fallback esaurisce la quota (429), Jarvis lo comunica senza mostrare
l'errore tecnico e libera la coda; anche 503 e timeout producono un messaggio
comprensibile quando i tentativi disponibili non vanno a buon fine.
Un watchdog indipendente libera la FIFO dopo 60 secondi per gli altri comandi;
per l'analisi Vision concede 150 secondi dall'inizio dell'esecuzione e registra
gli stack dei thread coinvolti. Questo include tutti i tentativi e la cattura:
ritardi aggiuntivi possono comunque consumare il tempo disponibile per Gemma.
Anche il timeout ordinario e il timeout del processo Vision sono di 150 secondi.
La visione gira in un processo separato che viene terminato se l'operazione
scade o viene annullata. Per sbloccare manualmente, scrivi oppure pronuncia
«Jarvis, sblocca la coda». I risultati tardivi vengono ignorati.

La suite automatica non-live imposta Qt offscreen tramite `tests/conftest.py`;
i test che creano finestre QtWebEngine reali vengono saltati in questa modalita
per evitare crash nativi. Non serve impostare `CI=true`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs -m "not live and not benchmark"
```

I test del viewer sono isolati con `pytest-isolated`, incluso nelle dipendenze
di test, per evitare la condivisione dello stato Qt con la suite principale.
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

## Background Tasks and Workers

JARVIS supports asynchronous task delegation via `delegate_task`.
Workers are currently registered at startup in `main.py`:

- `writer` — generates text (LLM) and saves to
  `~/Desktop/JARVIS Tasks/`. Timeout 300s, tools: `write_file`.
- `browser` — opens URLs in the embedded browser panel.
  Timeout 180s, tools: `embedded_browser`, `read_page`.

Worker configuration (system prompt, timeout, tools allowlist)
is defined in the respective worker classes
(`core/task_worker_impl.py`). To add a new role, register a new
worker class in `main.py` at startup.

Note: a `config/task_roles.json` mechanism is not implemented.
If needed, it can be added by extending the registration logic
in `main.py` to read a JSON file at startup.

Only the main session speaks; completion notifications wait until JARVIS is
idle and group nearby completions. The `writer` uses an isolated Gemini call.
The `browser` returns readable page text; at most two embedded task browsers
run concurrently, with additional requests opened in the external browser.
Task indicators in the HUD show status and progress and open the full result.
Cancellation is cooperative and does not roll back completed writes.

Task state (including prompts and results) is stored as unencrypted local JSON
at `%USERPROFILE%\.jarvis-vii\tasks.json`; do not share it if it contains
sensitive data. Tasks still `running` after restart become `failed` with
`interrupted_by_restart`.

Test mirati:

```powershell
python -m pytest -q tests\test_task_manager.py tests\test_worker_llm.py tests\test_task_worker_impl.py tests\test_task_browser_pool.py tests\test_task_orchestrator.py tests\test_hud_bridge_integration.py
```

## Documenti

- `docs/n8n/README.md` — configurazione del bridge n8n e workflow "echo" di prova.
- `docs/CONNETTORI.md` — prerequisiti OAuth e stato dei connettori disponibili.
- `NOTICE` — attribuzioni e licenze.
- `INSTALL_WINDOWS.md` — guida di installazione.
- `SECURITY.md` — checklist di sicurezza.
- `LIMITI.md` — limiti noti e parti DA VERIFICARE.

## Licenza

Uso **personale / non commerciale**. Componenti sotto CC BY-NC 4.0 (© FatihMakes), GEV MIT, ASTRALIS Apache-2.0. Vedi `NOTICE` e `LICENSE`.
