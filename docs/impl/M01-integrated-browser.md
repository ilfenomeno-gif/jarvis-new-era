# M01 — Integrated browser

## Obiettivo

Aprire nomi di siti e URL HTTP(S) dentro Jarvis, offrendo indietro, avanti,
ricarica e chiusura con ritorno alla vista precedente. Tenere il browser
separato dalla pagina GEV e dal suo lifecycle.

## 1. Diagnosi (stato reale del repo, rischi, dipendenze)

- `ui.py:2415` definisce `MainWindow`; `ui.py:2541` e `ui.py:2545` creano
  gli stack esistenti. `_center_split` mostra HUD/camera/GEV sopra il pannello
  `QTextEdit`.
- `QWebEngineView` è già disponibile nel venv ed è usata in `ui.py:2551` per
  GEV. Un secondo widget browser è quindi fattibile senza nuove dipendenze.
- `JarvisUI` espone metodi thread-safe via signal (`_content_sig`,
  `_gev_send_sig`); Gemini dispatcha gli strumenti in `main.py:_execute_tool`.
  L'implementazione deve usare lo stesso confine segnali/slot.
- `actions/browser_control.py` esegue automazione Playwright/browser esterno;
  non è il browser integrato richiesto. Lo strumento core `open_website`
  sarà distinto e dichiarato in `main.py`.
- Il browser non deve condividere o rimpiazzare il `QWebEnginePage` GEV. I
  redirect/navigazioni browser devono bloccare schemi diversi da HTTP(S).
- Nessuna dipendenza nuova richiesta. Ambiente verificato: Python 3.13.7,
  PyQt6 6.11.0, Qt/WebEngine 6.11.2.

## 2. Procedura (sotto-passi atomici: file → modifica → criterio di successo)

1. `core/browser_url.py` → normalizzare alias di sito e host senza schema,
   validare hostname/porta e consentire soltanto HTTP(S). Criterio: unit test
   pass per alias e URL validi, rifiuto esplicito degli schemi non ammessi.
2. `ui.py` → creare un contenitore browser dedicato con barra indirizzo,
   QWebEngineView e azioni indietro/avanti/ricarica/chiudi. Criterio: apertura e
   ritorno allo stack selezionato prima dell'apertura; `loadFinished` non
   riuscito produce stato/log esplicito.
3. `ui.py` → instradare le richieste browser da `JarvisUI` attraverso segnali
   collegati a slot GUI; isolare la pagina da GEV. Criterio: nessun accesso
   widget nel thread asyncio/plugin e le azioni GEV continuano a selezionare il
   proprio stack.
4. `main.py` → dichiarare `open_website(url)` e instradarlo a
   `JarvisUI.open_url_in_webview`; aggiornare la descrizione di `open_app` per
   evitare ambiguità. Criterio: Gemini può richiedere YouTube o un host; errori
   di validazione diventano risposta esplicita.
5. `tests/test_browser_url.py` e test UI mirati → proteggere normalizzazione e
   comportamenti non distruttivi. Criterio: suite focused verde.

## 3. Modifiche per file

- `core/browser_url.py` (nuovo): normalizzazione e allow-list schema URL.
- `ui.py`: widget browser dedicato, segnali/slot, cronologia, stato/caricamento.
- `main.py`: function declaration core, routing strumento, descrizione open_app.
- `tests/test_browser_url.py` (nuovo) e test UI mirati se compatibili col runner.
- `docs/impl/M01-integrated-browser.md`, `PROGRESS.md`: piano ed evidenza.

## 4. Test plan (automatici + manuali)

- Unit: alias `YouTube`, URL `example.com`, HTTP e HTTPS; valori vuoti,
  `file://`, `javascript:`, `data:`, `ftp://`, URL senza host, credenziali e
  porte non valide.
- UI: servire `tests/fixtures/` con `python tests/serve_fixtures.py` e usare
  `http://127.0.0.1:<porta>/page_simple.html`; verificare titolo e paragrafo,
  link a `page_simple_2.html`, indietro/avanti/ricarica e chiusura che ripristina
  HUD o GEV. URL invalido non naviga; browser e GEV restano widget distinti.
  Il test va eseguito nell'app funzionante, non con un harness Qt isolato.
- Gemini/tool: declaration `open_website`, dispatch, errore esplicito su input
  invalido e nessuna azione widget fuori dal thread GUI.
- Regression: `pytest` mirato (poi suite Jarvis); GEV lifecycle e test già
  presenti.
- Smoke: avvio Jarvis dopo modifica, finestra e plugin GEV pronti. Audio/Live
  Gemini si riportano solo se effettivamente osservati.

## 5. Criteri di accettazione (checklist PASS/FAIL)

- [ ] `http://127.0.0.1:<porta>/page_simple.html` mostra titolo e paragrafo;
  il link apre `page_simple_2.html`, indietro/avanti ripristinano la cronologia
  e chiudi ripristina la vista precedente. Convalida live ancora bloccata.
- [x] `file://`, `javascript:`, `data:`, FTP e altri schemi sono rifiutati dal
  normalizzatore; test focused passati.
- [x] La richiesta URL dal wrapper Jarvis passa attraverso un signal Qt; test
  unitario pass.
- [x] La logica stack conserva e ripristina la vista precedente; test unitario
  con doppia apertura pass.
- [x] GEV resta su widget/pagina distinti; app avviata dopo le modifiche, GEV
  pronto con 30 tool MCP.
- [ ] Il redirect a uno schema non HTTP(S) viene bloccato nel WebEngine live;
  l'allow-list è implementata, ma non esiste ancora evidenza runtime.

## 6. Analisi di fattibilità del presente file (checklist GO/NO-GO + esito)

- [x] Componenti e percorsi verificati nel codice reale; i file nuovi sono
  marcati come da creare.
- [x] PyQt6/WebEngine sono presenti nell'ambiente corrente.
- [x] Nessuna sovrapposizione prevista col bridge GEV: browser e GEV hanno
  pagine e stack indipendenti.
- [x] Test automatici eseguibili localmente; una pagina HTTP locale copre il
  test UI senza dipendere da provider/API remoti.
- [x] Rollback definito.

**Esito: GO.**

## 7. Rollback (come tornare indietro)

Commit inversi del branch `feat/m01-integrated-browser`, in ordine. Non
modificare o eliminare file locali di configurazione; nessun force-push o
riscrittura della history.

## 8. Registro esecuzione (data, esito verifica, esito convalida)

- 2026-10-04: diagnosi eseguita su checkout reale; GO prima dell'implementazione.
- 2026-10-04: `core/browser_url.py` e `tests/test_browser_url.py` implementati;
  primo run 19/20 ha rilevato `localhost:porta/percorso`, correzione applicata;
  test URL iniziale **20/20 PASS**.
- 2026-10-04: completati UI Qt, dichiarazione/dispatch `open_website`,
  navigazione sicura e unit test; suite Jarvis **73/73 PASS**, compileall PASS,
  Pylance syntax/problemi senza errori.
- 2026-10-04: smoke app aggiornata mostra `JARVIS — MARK LII`; GEV/MCP pronto
  con 30 tool. La sessione Gemini resta `Connecting...`; il comando testo non
  dispatcha tool perché `JarvisLive._on_text_command` ritorna senza sessione.
- 2026-10-04: tre prove runtime Qt/WebEngine isolate terminate con crash nativo
  Windows `0xC0000409`, prima di produrre risultati; harness temporanei non
  sono stati mantenuti. Navigazione e history reali non sono state convalidate.
- 2026-10-05: aggiunte fixture HTTP locali (`page_simple.html`,
  `page_simple_2.html`) e server loopback su porta assegnata dal sistema;
  convalida nell'app non eseguita: non c'era un processo Jarvis attivo e la
  sessione Gemini non è stata verificata con una richiesta autenticata.
- 2026-10-05: `pytest -q`: 115 passed; `compileall` helper fixture e
  `git diff --check`: PASS. `python tests/serve_fixtures.py` ha assegnato la
  porta 49921; tutte le 5 pagine hanno risposto HTTP 200 e il test automatico
  conferma almeno 500 parole nella pagina lunga. Server arrestato dopo lo
  smoke test; nessuna pagina aperta nell'app Jarvis.
- Convalida: **BLOCKED**, in attesa di sessione Gemini attiva o verifica UI
  interattiva con ambiente Qt/WebEngine funzionante.

## 9. Recap finale

Il browser integrato è implementato, con URL HTTP(S) validati, dichiarazione
Gemini, segnali Qt, pagina distinta da GEV e controlli UI. Le fixture locali
riducono la prova funzionale a risorse deterministiche e offline. Navigazione,
cronologia e redirect live non sono stati convalidati nell'app reale; M1 resta
**BLOCKED**, non DONE, finché non sono osservati nell'app.

## Ciclo di revalidazione secondo PROCEDURA_IMPLEMENTATIVA_JARVIS.md

### Fase 1 — Diagnosi

- Meccanica: M1 browser integrato; stato iniziale **IMPLEMENTATA – NON
  CONVALIDATA**.
- Classe: **A da validare** per URL HTTP(S), browser panel e history già
  implementati; **B da esporre** per le fixture locali già aggiunte.
- Codice esistente: `core/browser_url.py::normalize_http_url` ammette solo
  HTTP(S), blocca credenziali e input con controlli; `ui.py::_open_url_in_webview`
  mostra il browser dedicato e mantiene la vista di ritorno;
  `ui.py::_on_browser_load_finished` registra success/failure;
  `ui.py::_SafeBrowserPage.acceptNavigationRequest` blocca schemi non web;
  `main.py` dichiara `open_website`. `actions/browser_control.py::browser_control`
  controlla il browser esterno via Playwright/native launcher e non duplica il
  pannello QWebEngine integrato.
- Vincoli letti: `PIANO_TECNICO_JARVIS.md`, `soul.md`, `readme.md`,
  `regole e vincoli/regole e vincoli.md`, più la procedura allegata.
- Dipendenze: PyQt6-WebEngine già installato; server fixture loopback locale;
  per L3 serve UI Jarvis visibile; il tool `open_website` dipende da Gemini
  Live, che non è stato osservato connesso; L4 richiede microfono/audio e
  sessione Live.
- Lacune `Da verificare`: caricamento HTTP nel QWebEngine reale, titolo e
  visibilità, back/forward/reload/close, redirect non HTTP(S), tool end-to-end.
- Livelli raggiungibili: L1 sì; L2 sì per normalizzazione URL e fixture HTTP;
  L3/L4 bloccati da prova visiva e connessione Gemini che l'utente deve
  eseguire/riportare.
- Conclusione: non è necessario modificare il browser prima di L2. Fermarsi
  prima delle prove GUI/Live evita di attribuire evidenza non osservata.

### Fase 2 — Piano implementativo

- Interfaccia esistente: `open_website(url: string)`; errore esplicito su URL
  vuoto/non HTTP(S)/malformato; azioni UI per indietro, avanti, reload e close.
- Frase suggerita: «Apro la pagina nel browser di Jarvis.»; errori: «L'indirizzo
  non è valido o il caricamento non è riuscito.»
- L2: chiamare `normalize_http_url` per URL locale valida e schemi non ammessi;
  servire `tests/fixtures/` e richiedere `page_simple.html` e
  `page_simple_2.html`.
- L3: in Jarvis con Gemini connesso, digitare il comando concordato per aprire
  la fixture; osservare titolo/contenuto, link, indietro/avanti/reload/chiudi e
  rifiuto redirect. Richiede conferma visiva dell'utente.
- L4: impartire comando vocale con microfono e confermare risposta parlata;
  non richiesto per il solo criterio UI e resta dipendente da Gemini/audio.
- File previsti: `core/browser_url.py` e `ui.py` solo se L2/L3 prova un bug;
  `tests/test_browser_url.py` per ogni fix riproducibile; questo documento,
  `OPEN_QUESTIONS.md` e `PROGRESS.md` per le evidenze.
- Rollback: un revert del solo commit di revalidazione, senza modificare la
  cronologia M1–M3.

### Fase 3 — Fattibilità

1. **SÌ** — file/funzioni reali letti in `core/browser_url.py`, `ui.py`,
   `main.py` e `actions/browser_control.py`.
2. **SÌ** — il browser esterno non duplica il widget QWebEngine integrato.
3. **SÌ** — navigazione usa URL HTTP(S), segnali Qt e allow-list già presenti;
   nessun comando di sistema o scrittura.
4. **SÌ** — `open_website` è distinto da `browser_control`.
5. **SÌ** — PyQt6/WebEngine e fixture sono già disponibili; Gemini Live non è
   prerequisito per L1/L2.
6. **SÌ** per L1/L2; **NO per ora** per L3/L4, richiedono rispettivamente
   prova visiva e Gemini/microfono dell'utente.
7. **SÌ** — rollback tramite revert del commit documentale/test del ciclo.
8. **SÌ** — il test URL non interagisce con ciclo audio o Gemini.
9. **SÌ** — schemi non HTTP(S) e credenziali URL sono rifiutati; fixture
   servite solo su loopback.
10. **SÌ** — commit singolo del blocco di revalidazione e delle relative
    evidenze, senza merge/push.

**Verdetto Fase 3: PROCEDI per L1/L2; L3/L4 BLOCCATI in attesa della prova
visiva/Live dell'utente.**

### Fase 4 — Implementazione

Nessuna modifica al codice applicativo: M1 è già implementata e la fase 1 non
ha evidenziato una correzione necessaria. Le fixture/server locali sono già
presenti sul branch base `feat/m01-m03-fixtures`; il ciclo corrente aggiunge
solo evidenze e, se necessario, test di regressione.

### Fase 5 — Verifica tecnica L1

- Comando: `python -m pytest -q` → **115 passed, 0 failed**.
- Comando: `python -m compileall -q core\browser_url.py ui.py main.py
  tests\test_browser_url.py tests\test_fixtures.py tests\serve_fixtures.py`
  → PASS.
- Comando: `git diff --check` → PASS.
- Gate: superato, nessun fallimento.

### Fase 6 — Convalida reale per livelli

- **L1 PASS:** suite, compileall e diff-check come sopra.
- **L2 PASS:** comando Python in `.venv` che avvia `create_server()` per le
  fixture, chiama `normalize_http_url` su
  `http://127.0.0.1:55852/page_simple.html`, esegue GET sulle pagine simple e
  simple_2 e valida HTTP 200, titolo/contenuto. La stessa invocazione rifiuta
  `javascript:alert(1)`. Output: entrambe le richieste HTTP 200; URL non sicuro
  rifiutato; server arrestato nel `finally`.
- **L3 BLOCCATO — prova visiva necessaria all'utente:** non è stata aperta una
  finestra Jarvis né il QWebEngine live. Il test deve dimostrare titolo e
  contenuto visibili, link, indietro/avanti/reload/chiudi e blocco redirect.
  L'utente deve avviare/verificare la finestra e riportare l'esito osservato.
- **L4 BLOCCATO — dipendenza esterna/utente:** il log più recente disponibile
  è storico (2026-09-08) e contiene `Connecting...`; non dimostra lo stato
  attuale. Nessun `JARVIS online` è stato osservato in questo ciclo. La
  credenziale non è stata trasmessa e il codice Gemini Live è rimasto invariato.
- Errore provato a L2: schema JavaScript rifiutato. Errori live di caricamento
  e redirect restano da provare in GUI.

### Fase 7 — Aggiornamento documentazione/stato

Aggiornati questo registro, la tabella M1 in `PROGRESS.md` e il blocco Gemini /
azione manuale in `OPEN_QUESTIONS.md`. Stato coerente: L1/L2 PASS,
L3/L4 BLOCKED, M1 **IMPLEMENTATA – NON CONVALIDATA**; nessun merge.

### Fase 8 — Recap del ciclo

- Meccanica: M1 integrated browser.
- Branch: `feat/m01-browser-revalidation`; base
  `feat/m01-m03-fixtures`; codice browser implementato sul branch M1 originario.
- L1: PASS, 115 test.
- L2: PASS, normalizzazione URL e fixture HTTP locale provate.
- L3: BLOCCATO, verifica visiva nel Jarvis/QWebEngine richiesta all'utente.
- L4: BLOCCATO, stato Gemini Live e voce non osservati; B0 richiede verifica
  sicura dell'utente.
- Stato: IMPLEMENTATA – NON CONVALIDATA, con evidenza L2. Nessun merge/push.
- Prossima in coda: riprendere L3 M1 dopo evidenza visuale; quindi M2 → M3 →
  M4, solo ai livelli che non dipendono da decisioni o prove utente.
