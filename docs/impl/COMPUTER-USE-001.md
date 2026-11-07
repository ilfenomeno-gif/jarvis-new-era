# Computer Use — Fase A

## Stato e architettura

Fase A1 (terminale) e A2 (browser DOM) sono implementate in Python nel branch
`feat/computer-use-loop`. `JARVIS_COMPUTER_LOOP=1` abilita il nuovo percorso;
il default è `0`. Se il flag è spento, `actions/computer_loop.py` restituisce
il fallback informativo e le azioni preesistenti restano disponibili.

`core/computer_loop.py` coordina il planner (LLM predefinito), l'esecuzione,
la verifica per passo, gli eventi di memoria a breve termine, l'audit e fino a
tre retry. I piani sono limitati a 12 passi; azioni ripetute dopo un fallimento
sono soppresse. Le operazioni terminali tipizzate confinano i percorsi al
workspace; i comandi liberi passano da `TerminalAgent` e `TerminalGuard`.
`run_pytest` usa `shell=False`, cattura stdout/stderr e applica il timeout del
loop; se presente, seleziona esplicitamente `pytest.ini`.

Le azioni browser passano da `BrowserAutomation`, che serializza Playwright su
un thread dedicato. Usano testo accessibile, ruoli/nome, label e selettori DOM,
mai coordinate. Sono supportati navigazione HTTP(S), click, compilazione e
submit di form, back, titolo/testo, attesa di elementi, screenshot e controlli
HTML5 play/pause/seek/fullscreen/state. URL, titolo, selettori, testo, valori
dei campi, video e file screenshot possono essere verificati. Un fallimento
torna al planner con l'esito e la memoria dei tentativi. Non è previsto un
fallback a coordinate: se la pagina non espone il DOM, il passo fallisce e
richiede la futura Fase B.

La ricerca Google attende i risultati DOM e restituisce il testo leggibile
entro 6000 caratteri; la lettura diretta della pagina (`browser_automation`,
azione `read`) ha lo stesso limite. Un risultato vuoto o non disponibile
costituisce un errore esplicito, non un successo simulato. Il browser non usa
il profilo o i cookie personali; non aggira CAPTCHA o controlli di accesso.
Il consenso ai cookie resta una scelta dell'utente; se Google richiede una
verifica umana, la ricerca si interrompe senza tentare di superarla.

Ogni click browser e submit di form, oltre a ogni override della policy
terminale e al `git_commit` tipizzato, passa da `core.confirm.request`; un
rifiuto o una scadenza non eseguono l'azione. Il terminale A1 supporta solo
comandi non interattivi: PTY/sessioni interattive non sono implementate per
questa fase Windows.

`core/clipboard.py` espone `get()`, `set(text)`, `copy_selection()` e
`paste_into(target)`. Su Windows usa PowerShell `Get-Clipboard`/`Set-Clipboard`;
nel browser legge la selezione DOM, trasferisce il testo alla clipboard del
sistema e scrive/incolla con `navigator.clipboard` e `page.keyboard`. Errori
del backend clipboard sono espliciti, non convertiti in successi.

## Desktop e terminale visibile

Le azioni desktop esistenti sono disponibili come strumenti separati:
`open_app` avvia applicazioni supportate, `computer_screenshot` mostra lo
schermo nel pannello Computer Use, `computer_read_screen` restituisce testo OCR
locale al modello dopo conferma, `computer_task` riconosce testo visibile per
click/scrittura mirati e `computer_input` invia un singolo click, movimento,
pressione, scorciatoia, scroll o testo. `computer_settings` puo chiudere la
finestra/app attiva solo dopo conferma; non termina processi in background.
Ogni input desktop richiede conferma e ricontrolla la finestra in primo piano.
La lettura OCR non salva immagini o testo e limita la risposta a 6000 caratteri.

Per digitare in una console interattiva su Windows:

1. chiedere a JARVIS di aprire il terminale; `terminal_open_ext` apre un
   Command Prompt visibile dopo conferma;
2. verificare che la console sia in primo piano;
3. inviare il testo con `computer_input` (`type_text`), controllando il testo
   nella richiesta di conferma;
4. inviare `computer_input` (`press`, `key: "enter"`) separatamente dopo aver
   controllato la riga da eseguire.

L'allowlist di input desktop comprende ora `cmd.exe`, `conhost.exe`,
`powershell.exe`, `pwsh.exe`, `WindowsTerminal.exe` e `OpenConsole.exe`, oltre
alle applicazioni già supportate. `JARVIS_INPUT_ALLOWLIST` può restringere o sostituire
l'allowlist. Le conferme di digitazione/invio sono un controllo umano, non una
sandbox: non approvare comandi non compresi. Il percorso `computer_use_loop`
resta opt-in (`JARVIS_COMPUTER_LOOP=1`); con Harness è inoltre richiesto
`JARVIS_HARNESS=1`. Il runtime Harness riceve ora il registry e valida il goal
e il workspace contro il contratto dell'azione prima del dispatch. Il loop
automatico continua a usare `TerminalGuard`, senza shell operatori, e non
interagisce con terminali interattivi in modo autonomo.

Le prove desktop/web live sono opt-in:
`$env:JARVIS_RUN_COMPUTER_USE_E2E="1"; `
`python -m pytest -q -m live tests/test_computer_use_live.py`.
La prova del terminale digita un comando innocuo e controlla il titolo della
console. La ricerca Google si ferma se viene richiesto un consenso o una
verifica umana; il test opt-in seleziona "Rifiuta tutto" solo nella sessione
isolata e CAPTCHA/controlli anti-bot non vengono aggirati.

## Avvio

Il flag deve essere impostato prima di avviare Jarvis:

```powershell
$env:JARVIS_COMPUTER_LOOP = "1"
.\.venv\Scripts\python.exe main.py
```

Il loop è già inizializzato da `main.py` solo con il flag attivo e riceve gli
stessi `TerminalAgent` e `BrowserAutomation` delle azioni esistenti. Per
disabilitarlo, avviare una nuova sessione senza il flag o con valore `0`.
L'azione richiede un workspace esistente per contenere le modifiche locali e
gli screenshot. Timeout per subprocess e retry si configurano con
`JARVIS_COMPUTER_LOOP_TIMEOUT` (secondi, default `30`) e
`JARVIS_COMPUTER_LOOP_MAX_RETRIES` (default `3`).

Playwright era già presente. In questo ambiente il pacchetto è 1.58.0, mentre
la cache Playwright preesistente contiene Chromium 1208 (il launch predefinito
richiede 1248). Il benchmark ha usato il binario Chromium 145 già installato,
passato esplicitamente a `PlaywrightBrowser`. Per l'avvio standard installare
la revisione corrispondente con `python -m playwright install chromium`; in
alternativa impostare `PLAYWRIGHT_EXECUTABLE_PATH` al percorso assoluto di un
eseguibile Chromium esistente.

## Benchmark A1 — terminale

Comando riproducibile:

```powershell
.\.venv\Scripts\python.exe benchmarks\bench_computer_use.py
```

Il runner usa `ComputerLoop` reale, workspace isolati per le operazioni di
scrittura e il repository corrente per le scansioni read-only e pytest.
Il planner del benchmark è deterministico e fornisce piani predefiniti: i
risultati certificano il percorso di esecuzione/verifica, non la qualità del
planning LLM live. Non è stato eseguito alcun commit.

| # | Task | Esito | Passi | Retry | Tempo osservato | Risultato |
|---|------|-------|------:|------:|----------------:|-----------|
| 1 | Elenco `.py` nel progetto | PASS | 1 | 0 | 4613 ms | 320 file, output 7.817 byte |
| 2 | Dimensione totale dei `.log` | PASS | 1 | 0 | 1609 ms | 3 file, 103.995 byte |
| 3 | Crea cartella, copia e verifica file | PASS | 1 | 0 | 20 ms | Copia verificata nella fixture |
| 4 | Esegue pytest sul progetto | PASS | 1 | 0 | 4502 ms | `10 passed` |
| 5 | Cerca flag nei sorgenti Python | PASS | 1 | 0 | 2492 ms | 9 match |
| 6 | Rinomina `.jpeg` in `.jpg` | PASS | 1 | 0 | 18 ms | 2 file rinominati e verificati |
| 7 | Crea ZIP di backup | PASS | 1 | 0 | 25 ms | Archivio testato con `testzip()` |
| 8 | Trova owner porta 8080 | PASS | 1 | 0 | 25 ms | Nessun processo in ascolto |
| 9 | Conta righe Python del progetto | PASS | 1 | 0 | 1754 ms | 320 file, 85.055 righe |
| 10 | Crea branch e commit | BLOCCATO | 0 | 0 | — | Non eseguito: commit vietato dal task |

**Checkpoint A1: superato.** 9/10 task completati; tutti i 9 task eseguibili
sono riusciti senza intervento umano. Il decimo è escluso dal denominatore
operativo perché avrebbe creato un commit, esplicitamente vietato. Le scritture
sono avvenute solo in fixture temporanee.

## Benchmark A2 — browser

Comando riproducibile:

```powershell
.\.venv\Scripts\python.exe benchmarks\bench_computer_browser.py
```

Esegue Playwright Chromium headless reale contro un server HTTP effimero su
`127.0.0.1`; non contatta siti esterni. Per il benchmark le sole conferme a
click/submit vengono auto-accettate da un callback di test, esclusivamente
sulla fixture usa-e-getta. Nel processo Jarvis resta attiva la conferma UI.
Per il passaggio clipboard, il backend del sistema è sostituito da una clipboard
in memoria; il browser e i passaggi DOM/keyboard restano reali. L'esecuzione è
una misura funzionale singola, non un benchmark di latenza.

| # | Task | Esito | Passi | Retry | Tempo osservato | Verifica |
|---|------|-------|------:|------:|----------------:|-----------|
| 1 | Apri pagina e leggi titolo | PASS | 2 | 0 | 762 ms | Titolo atteso |
| 2 | Compila e invia form | PASS | 4 | 0 | 182 ms | Navigazione alla ricevuta |
| 3 | Clicca bottone col testo richiesto | PASS | 3 | 0 | 120 ms | Testo DOM `clicked` |
| 4 | Estrai paragrafo | PASS | 2 | 0 | 57 ms | Testo atteso |
| 5 | Naviga e torna indietro | PASS | 3 | 0 | 125 ms | URL ripristinato |
| 6 | Copia testo e incollalo in un campo | PASS | 3 | 0 | 110 ms | Valore input identico |
| 7 | Play, pause e `currentTime` video HTML5 | PASS | 4 | 0 | 1473 ms | Stati DOM e tempo letti |
| 8 | Attendi elemento differito | PASS | 2 | 0 | 890 ms | Selettore visibile |
| 9 | Screenshot di verifica | PASS | 2 | 0 | 103 ms | File esistente nel workspace |
| 10 | Chiudi cookie banner e continua | PASS | 4 | 0 | 153 ms | Banner chiuso, azione verificata |

**Checkpoint A2: superato, 10/10.** Le durate includono startup/navigazione
quando applicabile e variano tra esecuzioni; non sono SLO di produzione.

## Test e validazione

Comando pytest mirato:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c pytest.ini tests\test_memory_store_pool.py tests\test_brain_router.py tests\test_chat_orchestrator.py tests\test_hud_bridge_integration.py tests\test_sidecar_runtime.py tests\test_sidecar_smoke.py tests\test_computer_loop.py tests\test_computer_loop_browser.py tests\test_browser_automation.py tests\test_terminal_agent.py
```

Esito: **66 passed**. Include test del fallback con flag off, retry e
soppressione dei tentativi identici, confine workspace, audit/memoria,
conferma/cancellazione e flussi browser/clipboard Mock.

Ruff sui file nuovi e sui moduli computer-use/browser/clipboard: **pulito**.
`py_compile` dei nuovi moduli, benchmark, test e `main.py`: **passato**.
`git diff --check` circoscritto ai file del task: **pulito**. I controlli Ruff
separati su `main.py` e `core/confirm.py` rilevano 85 finding di lint già
presenti in quelle unità; non sono stati corretti fuori scope.

## Limiti, rischi e prossimi passi

- I piani dei benchmark A1/A2 sono deterministici: rimane da misurare il tasso
  di successo end-to-end con l'LLM configurato e richieste naturali.
- A2 verifica browser Chromium headless e pagine locali; autenticazione,
  cookie/profilo dell'utente, siti reali e protezioni dei siti non sono testati.
- La clipboard Windows PowerShell reale non è stata usata nel benchmark
  headless; è coperta da un backend fake nei test, mentre il trasferimento
  browser DOM/clipboard/keyboard è stato eseguito su Chromium reale.
- La disponibilità del banner di conferma richiede la UI Jarvis attiva. In
  modalità headless o senza callback l'azione resta rifiutata.
- Nessun commit, branch ulteriore o PR è stato creato durante questa fase.
- Prossimo passo: validare il planner LLM su task approvati e provare i flussi
  con un browser autenticato solo dopo aver definito il consenso e il profilo di
  rischio; la Fase B visiva resta separata.
