# M03 — Integrated page reader

## Obiettivo

Leggere ad alta voce il testo della pagina nel browser integrato Jarvis, con
estrazione DOM asincrona, sintesi offline in worker, testo limitato/chunked e
comando stop non bloccante.

## 1. Diagnosi (stato reale del repo, rischi, dipendenze)

- Il browser integrato M1 è in `MainWindow._browser_page` e supporta
  `runJavaScript`; il wrapper UI usa signal Qt per richieste provenienti dal
  thread Gemini.
- `read_active_page` esistente opera su browser esterni Playwright o screenshot
  e riassume il testo; non legge ad alta voce la QWebEngineView integrata.
- `core/accessibility.py` contiene `Pyttsx3Backend`, già dichiarato opzionale e
  selezionabile; `pyttsx3` è incluso in `requirements.txt` e importabile
  dall'interprete attivo.
- `Pyttsx3Backend.cancel()` attualmente acquisisce lo stesso lock mantenuto per
  tutta `runAndWait()`, quindi non può interrompere una frase lunga. Il driver
  pyttsx3 supporta un event loop esterno (`startLoop(False)`/`iterate`): il
  worker può controllare lo stop e chiamare `engine.stop()` nel thread che ha
  creato l'engine, evitando accesso COM cross-thread.
- `JarvisLive.speak()` reinvia testo a Gemini Live; non è adatto al flusso
  locale/annullabile del lettore e potrebbe competere con la voce già attiva.
  Il lettore userà pyttsx3 offline in un singolo worker dedicato; l'output audio
  Gemini verrà drenato/soppresso mentre la pagina è letta per non sovrapporre
  due voci.
- Browser non caricato/test live, audio host e output voce restano non
  verificati per i limiti M1/baseline; test automatici useranno un backend fake.

## 2. Procedura (sotto-passi atomici: file → modifica → criterio di successo)

1. `core/page_reader.py` (nuovo) → pulire e limitare testo pagina, spezzarlo in
   chunk e gestire un worker pyttsx3 dedicato con stop cooperativo. Criterio:
   test di limiti/chunk, stop concorrente e failure esposto.
2. `core/accessibility.py` → aggiungere `speak_interruptibly` con event loop
   esterno e rimozione del lock bloccante; lo stop event è controllato dal
   worker, che invoca `engine.stop()` sul thread dell'engine. Criterio: i test
   registrano che tutte le chiamate driver avvengono nello stesso thread.
3. `ui.py` → aggiungere read/stop signal, callback `document.body.innerText`,
   avvio worker solo dopo callback e cleanup alla chiusura. Criterio: callback
   non legge widget fuori GUI e worker non parte sul thread Qt.
4. `main.py` → dichiarare/instradare `read_page` e `stop_reading` e drenare
   l'output Gemini mentre il lettore pyttsx3 è attivo. Criterio: schema valido,
   nessuna collisione con `read_active_page` e audio non sovrapposto.
5. `tests/test_page_reader.py` e test UI/schema → verificare pagina vuota,
   testo >limite, chunk, stop entro timeout, errori, signal e dichiarazioni.
6. Aggiornare `PROGRESS.md`, `docs/REPO_MAP.md` e registro evidenze; eseguire
   suite completa e compileall. Audio live va marcato non verificato se
   dispositivo/ambiente non consentono ascolto.

## 3. Modifiche per file

- `core/page_reader.py` (nuovo): funzioni pure di pulizia/chunking e worker
  riusabile con backend iniettabile per test.
- `core/accessibility.py`: stop pyttsx3 privo del lock che blocca durante
  `runAndWait`.
- `ui.py`: signal/slot per estrazione DOM, callback asincrona, dispatch verso
  worker e stop/cleanup.
- `main.py`: function declarations e dispatch tool `read_page` /
  `stop_reading`; soppressione dell'audio Gemini durante la lettura locale.
- `tests/test_page_reader.py` (nuovo): test unitari di testo, worker e stop.
- `tests/test_browser_interaction.py`: integrazione UI se utile senza creare
  un processo Qt WebEngine isolato.
- `docs/impl/M03-screen-reader.md`, `docs/REPO_MAP.md`, `PROGRESS.md`:
  piano, architettura e recap.

## 4. Test plan (automatici + manuali)

- Pulizia whitespace, pagina vuota, testo enorme, limite complessivo e
  `len(chunk) <= 800`.
- Backend fake blocca su event; `stop()` deve cancellarlo e terminare il worker
  entro 2 secondi; nessun secondo worker simultaneo.
- L'engine fake pyttsx3 deve ricevere `say/startLoop/iterate/stop/endLoop` solo
  dal thread worker, incluso durante la cancellazione.
- I callback worker `on_started`/`on_finished` devono attivare/disattivare
  l'arbitraggio audio senza accesso diretto a widget.
- Errori nel backend devono arrivare al callback senza stampare testo pagina.
- Test signal wrapper e declarations `read_page`/`stop_reading`.
- Regression: suite completa, compileall e Problems/Pylance; smoke GEV/browser
  solo se runtime è disponibile.
- Manuale: servire `tests/fixtures/`, aprire
  `http://127.0.0.1:<porta>/page_long.html`, leggere e interrompere durante la
  voce; verificare GUI reattiva e assenza di audio sovrapposto. Ripetere con
  `page_empty.html` e verificare esito esplicito senza crash.

## 5. Criteri di accettazione (checklist PASS/FAIL)

- [ ] "Leggi la pagina" su `page_long.html` avvia la lettura; la GUI resta
  reattiva.
- [ ] "Smetti di leggere" interrompe entro pochi secondi.
- [ ] `page_empty.html` riporta "The active page contains no readable text"
  (o messaggio equivalente) senza crash;
  `page_long.html` resta entro il limite di estrazione e chunk <=800.
- [ ] Nessun conflitto con il TTS già usato da Jarvis.
- [ ] Il testo letto deriva dalla pagina attiva nel browser integrato.

**Esito criteri:** PASS parziale. Pulizia, limiti, chunk, gestione worker,
richiesta stop fake e segnali di arbitraggio sono coperti da test. Voce pyttsx3
su dispositivo reale, click/estrazione nel WebEngine live e assenza di
sovrapposizione audio reale non sono stati verificati.

## 6. Analisi di fattibilità del presente file (checklist GO/NO-GO + esito)

- [x] Browser, QWebEnginePage, signal UI, `Pyttsx3Backend` e dispatcher Gemini
  esistono; helper e tool M3 sono esplicitamente nuovi.
- [x] Pyttsx3 è dichiarato e importabile nell'ambiente attivo; nessuna nuova
  dipendenza necessaria.
- [x] Worker fake rende riproducibili test di stop senza audio/dispositivo.
- [x] Ambito separato dal tool browser esterno e dal TTS conversazionale
  Gemini; il lock cancel bloccante è una dipendenza direttamente coinvolta.
- [x] Rollback tramite commit inversi del solo branch M3.

**Esito: GO.**

## 7. Rollback (come tornare indietro)

Invertire i commit M3 in ordine; non modificare i branch M0–M2 o configurazioni
audio/chiavi. Non usare force-push o riscrittura history.

## 8. Registro esecuzione (data, esito verifica, esito convalida)

- 2026-10-04: diagnosi basata su `IMPLEMENTATION.md`, browser integrato,
  accessibility, TTS e dichiarazioni/dispatch reali; GO prima del codice.
- 2026-10-04: aggiunti worker pyttsx3, pulizia/chunking, stop cooperativo con
  event loop esterno sul thread engine, estrazione asincrona DOM e gate che
  drena l'audio Gemini durante la lettura offline.
- `pytest -q`: 111 passed; `compileall` sui file M3: PASS; Problems/Pylance:
  nessun errore; `git diff --check`: PASS.
- Import check `main`: PASS, 37 tool dichiarati e nessun nome duplicato;
  helper page reader importato e testo breve segmentato correttamente.
- 2026-10-05: aggiunte fixture deterministiche `page_long.html` (oltre 500
  parole) e `page_empty.html`; test audio/browser live non eseguito.
- 2026-10-05: suite cumulativa `pytest -q`: 115 passed; `compileall` delle
  utility fixture: PASS. La risposta del dispositivo audio e la lettura del
  DOM nell'app reale restano non testate.
- Convalida live: BLOCKED; baseline segnala che l'output audio host non produce
  audio e M1 non ha sessione Gemini/browser verificabile. Il package `pyttsx3`
  è importabile, ma non è stata avviata sintesi reale né modificata alcuna key.

## 9. Recap finale

Lettore integrato implementato in modo bounded, asincrono e interrompibile;
l'output Gemini viene drenato mentre la voce offline è attiva. Le fixture
offline coprono pagina lunga e vuota. M3 resta BLOCKED in attesa della
convalida audio/WebEngine live; non si presume che pyttsx3 produca audio
funzionante sull'host.
