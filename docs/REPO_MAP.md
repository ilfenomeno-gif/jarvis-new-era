# Mappa del progetto desktop JARVIS

Ricognizione M0 eseguita il 2026-10-04 sul checkout locale del repository
`ilfenomeno-gif/jarvis-ultimate`, originariamente sul branch
`feat/m00-repo-discovery`. I cicli successivi usano un branch dedicato ciascuno.

> Questa è la mappa storica della sottocartella app, ora inclusa in
> `jarvis-new-gen/Mark-LIV-main/`. I branch e i dettagli macchina qui sotto
> descrivono la ricognizione dell'epoca, non l'albero Git corrente.

## Struttura

```text
.
├── actions/       Azioni operative invocate dall'assistente (browser, sistema, web)
├── agents/        Agenti specializzati
├── config/        Configurazione locale e certificati; i segreti non sono stati letti
├── core/          Gemini, loader azioni/plugin, guardrail, accessibilità, audio e TTS
├── dashboard/     Server e asset del controllo remoto
├── docs/          Documentazione di integrazione e documenti implementativi
├── memory/        Configurazione, memoria e preferenze runtime
├── plugins/       Plugin caricabili, incluso il bridge MCP di GEV
├── tests/         Test pytest del progetto
├── main.py        Entry point e ciclo asincrono Gemini Live
├── ui.py          Applicazione desktop PyQt6 e widget
├── plugin_manager.py
├── requirements.txt
└── IMPLEMENTATION.md
```

Le cartelle `__pycache__`, `.venv`, `.pytest_cache` e `.vscode` sono presenti
localmente e non sono sorgenti applicative.

## Entry point e avvio

- `main.py:2276` definisce `main()`; `main.py:2312` è il guard dell'entry point.
- `main()` costruisce `JarvisUI("face.png")`, esegue `JarvisLive.run()` in un
  thread dedicato e avvia il loop Qt tramite `ui.root.mainloop()`.
- `ui.py:4568` definisce `JarvisUI`; crea/riusa `QApplication`, istanzia
  `MainWindow` e mostra la finestra.
- `ui.py:2415` definisce `MainWindow(QMainWindow)`.

## Interfaccia e navigazione esistente

- UI desktop: `ui.py`, PyQt6.
- `QStackedWidget` è importato in `ui.py:33` e usato per `_hud_cam_stack`,
  `_gev_stack` e (dopo M1) `_main_content_stack`. Quest'ultimo alterna il ramo
  HUD/camera/GEV e la pagina browser separata.
- `QWebEngineView` è importato in `ui.py:36`: una pagina serve GEV, una pagina
  browser è stata aggiunta in M1. `_GEVWebEnginePage` intercetta il bridge JSON
  `GEV_MSG:`; `_SafeBrowserPage` applica una allow-list di schemi HTTP(S).
- `ui.py:3862` crea il pannello contenuti basato su `QTextEdit`, non un browser.
- La navigazione URL attuale di `actions/browser_control.py` usa Playwright e
  `webbrowser.open`; non fornisce una scheda web dentro la finestra Jarvis.
- **M1 adattata alla struttura reale:** browser e GEV hanno pagine distinte;
  il browser è commutato con segnali Qt e conserva la vista precedente. La
  navigazione HTTP live non è ancora convalidata, vedi
  `docs/impl/M01-integrated-browser.md`.
- **M2:** `main.py` dichiara `press_key` e `click_link`; `ui.py` instrada
  richieste con segnali Qt e usa `core/browser_interaction.py` per whitelist,
  payload JSON e script DOM. La convalida su pagina/gioco reale resta bloccata.
- **M3:** `read_page` estrae testo limitato da `document.body.innerText` con
  callback asincrona; `core/page_reader.py` normalizza a 20.000 caratteri,
  segmenta a 800 e parla in un worker pyttsx3. `stop_reading` usa `engine.stop`;
  l'audio Gemini viene drenato mentre il worker è attivo. La sintesi reale non è
  convalidata per il warning audio della baseline.

## Azioni, plugin e Gemini

- Le function declarations core sono `TOOL_DECLARATIONS` in `main.py:178`.
- `core/plugin_loader.py` scopre e valida `plugins/*.py`, fornisce le
  dichiarazioni e instrada le esecuzioni tramite `PluginRegistry`.
- `JarvisLive.__init__` (`main.py:871`) scopre i plugin; il loro hook `start`
  viene eseguito in un thread dedicato. Le dichiarazioni core e plugin sono
  passate a Gemini nella configurazione Live in `main.py:1160`.
- Le chiamate funzione Gemini sono elaborate nel receive loop
  (`main.py:1650`) e `_execute_tool` (`main.py:1188`) instrada gli strumenti
  core e, in fallback, il plugin registry.
- `plugins/gev_plugin.py` definisce il plugin GEV e il ciclo server/MCP.
  `ui.py` comunica con il bridge tramite segnali Qt, incluso `_gev_send_sig`;
  il plugin non deve manipolare widget Qt direttamente.
- **M1 adattata alla struttura reale:** registrare lo strumento browser nelle
  dichiarazioni core e dispatch esistente, oppure usare un plugin solo se la
  verifica dei segnali Qt dimostra un percorso appropriato; mai chiamare un
  widget dal thread del plugin.

## Versioni e dipendenze osservate

- Sistema: Windows.
- Interprete selezionato del checkout: Python 3.13.7 (venv `.venv`).
- PyQt6 6.11.0; Qt runtime 6.11.2; PyQt6-WebEngine 6.11.0 / Qt WebEngine 6.11.2.
- `pytest` è installato. `pyttsx3` è elencato nelle dipendenze e presente
  nell'ambiente; `core/accessibility.py` espone `Pyttsx3Backend`, con chiamate
  sincrone protette da lock, quindi M3 non deve invocarle sul thread GUI.
- `core/tts.py` contiene altri backend TTS di Jarvis; M3 usa pyttsx3 isolato in
  worker e sopprime l'output Gemini per evitare sovrapposizioni.
  `Pyttsx3Backend.speak_interruptibly` pilota l'event loop esterno nel worker;
  `engine.stop()` viene chiamato dallo stesso thread, senza blocco del lock
  mantenuto da `runAndWait()`.
- Il file locale `config/api_keys.json` esiste ma non è stato aperto né copiato.
  `.env.local` non è stato letto o modificato.

## Ipotesi richieste dalla guida

| Ipotesi | Esito | Evidenza reale |
|---|---|---|
| `ui.py` | **CONFERMATA** | Contiene `JarvisUI` e `MainWindow`, il loop Qt, gli stack e la QWebEngineView GEV. |
| `plugins/gev_plugin.py` | **CONFERMATA** | Definisce `PLUGIN`, schema azione e lifecycle del server GEV/MCP. |
| `QWebEngineView` | **CONFERMATA** | Usata per GEV e per il widget browser separato aggiunto in M1; caricamento live browser ancora da convalidare. |
| `QStackedWidget` | **CONFERMATA** | Gli stack iniziali GEV/HUD sono confermati; M1 aggiunge lo stack contenitore che alterna HUD/GEV e browser. |

## Baseline prima delle modifiche M0

Avvio osservato il 2026-10-04, prima di copiare la guida o creare documenti:

- `main.py` è rimasto attivo; la finestra `JARVIS — MARK LII` è stata enumerata
  con titolo/coordinate/dimensione via API finestre desktop.
- stdout: discovery completato con **18 plugin attivi, 0 rifiutati**.
- stdout/log GEV: Vite pronto su `127.0.0.1:4173`, MCP connesso con **30 tool**,
  messaggio `GEV: pronto`.
- Stato Gemini: `Connecting...`; una connessione Live riuscita non è stata
  osservata durante la finestra di verifica.
- Warning stderr: `SetProcessDpiAwarenessContext() failed: Accesso negato`.
- Audio: `host API reports success but moves no audio ... skipping it`;
  inizializzazione elenca dispositivi MME, ma il funzionamento audio non è
  convalidato.
- Nessuna chiave o contenuto di file segreti è stato letto o registrato.

Questa baseline prova l'avvio del processo, la UI visibile, il discovery e il
plugin GEV; non prova una sessione Gemini completa, input microfono o output
audio.
