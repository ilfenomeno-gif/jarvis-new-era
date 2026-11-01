# IMPL-000 — Validazione live M1-M4

Data: 2026-10-06   Branch: `feat/000-validazione-live`   Stato: IN CORSO — F1-F4 COMPLETATE, IN ATTESA DELLE PROVE LIVE

## 1. Obiettivo

Chiudere la validazione live di voce e delle meccaniche M1–M4 (browser integrato, interazione web, screen reader e GPU), raccogliendo prove osservabili senza confondere test automatici o mock con esiti live.

## 2. Diagnosi (F1)

- Stato attuale: **IMPL-NON-VALIDATA** nel complesso; il supporto GPU è parziale e le prove live sono aperte.
- Evidenza acquisita il 2026-10-06: il controllo dei processi non ha trovato processi Jarvis/Python; il log storico disponibile riporta `Connecting...`, non una connessione Gemini attiva. Non sono state eseguite prove live in questa F1.
- File esistenti coinvolti:
  - `main.py` — modello Gemini Live, stream microfono/audio, dispatch dei tool e tool `system_status`.
  - `ui.py` — browser integrato, interazione WebEngine, estrazione DOM, screen reader e percorso di lettura GPU.
  - `core/browser_url.py` — normalizzazione URL e policy HTTP(S).
  - `core/browser_interaction.py` — whitelist tastiera e payload per click/testo e tasti.
  - `core/page_reader.py` e `core/accessibility.py` — pulizia/chunk del testo, worker TTS e cancellazione.
  - `actions/system_monitor.py` — metriche di sistema; carico GPU via NVML/`ctypes` o `pynvml`.
  - `main.py:969-970` e `main.py:1157-1162` — collegamento del segnale reader al flag di arbitraggio audio; `main.py:1840-1843` — drenaggio dei chunk Gemini durante la lettura.
  - `tests/test_browser_url.py`, `tests/test_browser_interaction.py`, `tests/test_page_reader.py`, `tests/test_fixtures.py` — verifiche automatiche esistenti, incluse verifiche con mock.
  - `tests/fixtures/page_simple.html`, `tests/fixtures/page_long.html`, `tests/fixtures/page_empty.html`, `tests/fixtures/snake.html` — pagine per le prove del browser.
- Dipendenze: Windows e dispositivi audio per la prova voce; configurazione Gemini già presente, rete e disponibilità del modello; PyQt6/WebEngine; motore TTS locale; driver NVIDIA/NVML per una misura GPU numerica. Non leggere o trasmettere credenziali durante le verifiche.
- Rischi:
  - Una prova di connessione Gemini o audio richiede microfono, output audio e credenziali locali; non può essere sostituita da mock.
  - I test correnti non attestano comportamento visivo WebEngine né click/tasti su un sito reale.
  - Il segnale `_page_reader_audio_sig` è collegato in `main.py` a `_set_page_reader_audio_active`; il playback Gemini drena i chunk ricevuti invece di riprodurli mentre il lettore locale è attivo. Il wiring è presente nel codice, ma l'assenza di sovrapposizione udibile non è stata ancora provata live.
  - La specifica ROADMAP parla di `nvidia-smi` read-only, ma il codice corrente non lo invoca: `actions/system_monitor.py` prova `pynvml` e quindi NVML via `ctypes`; il modulo dichiara esplicitamente l'assenza di subprocess. `system_status` espone `gpu_percent`, potenzialmente `None`. Non è stata trovata una query dedicata a VRAM, temperatura GPU, driver o processi.
  - L'eventuale uso di log storici come prova live produrrebbe una falsa attestazione.
- Sforzo stimato: 1–2 ore di verifiche automatiche e sessione live; stima indicativa, non misurazione.
- Aggiornamento automatico 2026-10-06: tutte le cinque fixture sono state richieste dal server locale temporaneo con HTTP 200; il server è stato arrestato e il thread terminato. Il probe NVML del processo ha restituito `gpu_percent=24.0` in quel campione. Queste osservazioni non provano il caricamento nella GUI né la risposta vocale Gemini.

### Esiti della diagnosi per componente

| Componente | Evidenza nel codice | Stato F1 |
|---|---|---|
| Voce (baseline) | `JarvisLive`, modello `LIVE_MODEL`, connessione Live e stream microfono/audio esistono; nessuna sessione o risposta audio corrente è stata osservata. | IMPL-NON-VALIDATA |
| M1 — Browser integrato | `open_website`, normalizzazione HTTP(S), navigazione QWebEngine e controlli UI presenti; caricamento e cronologia non osservati live. | IMPL-NON-VALIDATA |
| M2 — Interazione web | `press_key` e `click_link` registrati; whitelist tasti, escaping JSON e protezione da click ambiguo presenti; azione in WebEngine/Snake non osservata live. | IMPL-NON-VALIDATA |
| M3 — Screen reader | `read_page`/`stop_reading`, estrazione DOM, worker e connessione al gate audio Gemini presenti; TTS e assenza di sovrapposizione non ascoltati live. | IMPL-NON-VALIDATA |
| M4 — GPU | `system_status` riporta carico GPU da NVML, non da `nvidia-smi`; nessuna query GPU dedicata né prova live. | PARZIALE |

## 3. Procedura (F2)

Approccio: **validazione dell'implementazione esistente**, senza aggiungere una seconda implementazione GPU o modificare i guardrail. Motivazione: i componenti principali sono presenti; la lacuna primaria è l'evidenza end-to-end. La procedura riconosce l'implementazione GPU via NVML, registra lo scostamento dal requisito `nvidia-smi` della specifica e non introduce subprocess in questa meccanica.

| Step | Descrizione | File toccati | Test/verifica |
|------|-------------|--------------|---------------|
| 1 | Eseguire suite e compilazione richieste senza leggere configurazioni o credenziali. | Nessuno | `python -m compileall .`; `python -m unittest discover -s tests -v`; pytest e compile mirato come controlli aggiuntivi. Registrare output e limiti. |
| 2 | Servire fixture locali; aprirle nel browser integrato e provare navigazione. | Nessuno | Verificare risposta HTTP e osservare in UI titolo, contenuto, indietro, avanti e ricarica. |
| 3 | Provare click univoco, tasti consentiti e rifiuto input non ammessi su Snake. | Nessuno | Annotare risultato UI/log; usare solo fixture locale, senza sito o account reale. |
| 4 | Provare estrazione DOM, TTS, stop, pagina vuota e gate audio Gemini. | Nessuno | Registrare reattività, stop e sovrapposizione percepita; i test unitari non provano l'audio live. |
| 5 | Provare voce Gemini e `system_status` nella sessione Jarvis reale. | Nessuno | Annotare connessione e risposta; GPU riportata solo se misurata da NVML, altrimenti indisponibilità esplicita. |
| 6 | Aggiornare questa scheda con gli esiti e non procedere a 001 prima del recap di 000. | Solo questo IMPL | Rileggere F7 e verificare lo stato Git; niente staging/commit/push prima del recap. |

Nessuna dipendenza software nuova è prevista. Le prove GUI, microfono, audio e GPU reale richiedono dispositivi e sessione live disponibili e non sono sostituibili con test mock.

## 4. Criteri di accettazione

1. La verifica automatica di F6 è registrata con output reale; non prova da sola alcuna interazione live.
2. «Apri http://127.0.0.1:<porta>/page_simple.html» → Jarvis mostra nel browser integrato titolo e contenuto della fixture; il pulsante UI Indietro/Avanti ripristina le due pagine dopo aver aperto il link della pagina successiva.
3. «Clicca il link Leggi pagina successiva» → la fixture apre `page_simple_2.html`; «Premi la freccia destra» sulla fixture Snake → il gioco reagisce al tasto consentito; `Tab` non deve essere accettato dal tool `press_key`.
4. «Leggi ad alta voce la pagina» su `page_long.html`, poi «Smetti di leggere» → TTS udibile e arrestato; GUI reattiva e nessuna sovrapposizione Gemini udibile.
5. La stessa richiesta su `page_empty.html` → messaggio esplicito di assenza di testo, senza crash.
6. «Rispondi: test voce completato» → connessione Gemini osservabile e risposta udibile; non dedurre il successo da log storici.
7. «Qual è il carico della GPU?» → `system_status` riporta una percentuale soltanto se NVML la rileva, altrimenti l'indisponibilità è dichiarata; nessuna affermazione che `nvidia-smi` sia usato.
8. La meccanica è marcata `VALIDATA` solo dopo la raccolta degli esiti live di voce e M1–M4; il supporto GPU parziale deve restare esplicitamente descritto.

## 5. Rollback

Il piano non prevede modifiche al codice applicativo. Per annullare il solo documento, rimuovere `docs/impl/IMPL-000-validazione-live-base.md` con una modifica tracciata o revertire il commit che lo introduce. Non eliminare file non tracciati preesistenti, non ripristinare l'intero checkout e non alterare configurazioni o credenziali.

## 6. Diagnosi di fattibilità (F4)

- [x] Punti d'ingresso, tool Gemini e fixture della procedura verificati nel checkout.
- [ ] Compatibilità completa delle dipendenze con Python 3.11/3.12 non verificata; i test correnti usano Python 3.13.7.
- [x] Procedura sequenziale e separazione tra test automatici, UI e prove live.
- [x] Nessuna azione distruttiva, dipendenza pagata, OAuth o accesso a segreti introdotti.
- [x] Ogni step ha una verifica; le prove hardware/UI sono chiaramente live.
- [x] Criteri osservabili; i valori GPU sono accettati solo se NVML li restituisce.
- [x] Rollback limitato alla scheda; non è richiesto rollback applicativo.
- [x] Nessun impatto aggiuntivo sulla latenza: il percorso audio non viene modificato.
- [x] Limiti di GUI, microfono, audio e driver GPU dichiarati.
- [x] Scostamento tra requisito `nvidia-smi` e implementazione NVML documentato, non mascherato.

**Verdetto F4: GO CON MODIFICHE.** Si può procedere con la validazione del comportamento attualmente implementato, mantenendo esplicito il gap: la specifica cita `nvidia-smi`, mentre il codice rileva GPU via NVML. Questa meccanica non introduce subprocess o modifiche applicative senza una richiesta o un bug osservato. La compatibilità Python 3.11/3.12 non è dimostrata dal runtime corrente.

## 7. Log di implementazione (F5)

- Nessuna modifica al codice applicativo prevista per il perimetro corrente.
- F5: N/A per la validazione della meccanica esistente. Eventuali fix richiederanno una diagnosi del problema osservato, aggiornamento di questo IMPL e nuova verifica di fattibilità prima di modificare codice.

## 8. Verifica (F6)

- `python -m compileall .`: **FALLITO**, exit code 1; scansione include `.venv` e riporta `SyntaxError: invalid character '\u2202' (U+2202)` nel test installato `mediapipe/tasks/python/test/text/text_embedder_test.py` (riga 113 secondo la precedente cattura completa). Il pacchetto non è stato modificato.
- Compilazione mirata `python -m compileall -q main.py ui.py core actions tests`: **PASS**, exit code 0 (rieseguita in questo turno).
- `python -m unittest discover -s tests -v`: **NESSUN TEST TROVATO**, exit code 5 (`Ran 0 tests`).
- Suite configurata nel repository `python -m pytest -q`: **PASS, 115 passed in 1.36s**, exit code 0.
- Tutti i comandi sono stati eseguiti con `.venv` Python 3.13.7. Nessuna credenziale è stata letta o trasmessa.
- I risultati storici in `PROGRESS.md` non sono usati come sostituti di questi esiti.

## 9. Convalida (F7)

| Criterio | Esito | Note |
|----------|-------|------|
| 1. Suite automatica e compilazione | PARZIALE | Questo turno: pytest 115 pass/1.36s; compile mirato PASS; `compileall .` exit 1 per SyntaxError Mediapipe dentro `.venv`; unittest exit 5, 0 test. |
| 2. Fixture HTTP | PARZIALE L2 | Server locale temporaneo: GET 200 per page_simple, page_simple_2, page_long, page_empty e snake; server chiuso. La UI WebEngine, cronologia e controlli restano da validare live. |
| 3. Click, tasti e rifiuto input non ammessi | DA VALIDARE LIVE | Contratti e whitelist hanno test automatici, ma nessuna azione WebEngine/Snake è stata osservata live. |
| 4. Lettura lunga, stop e assenza di sovrapposizione | DA VALIDARE LIVE | Servono WebEngine e ascolto audio reali. |
| 5. Pagina vuota | DA VALIDARE LIVE | Verificare il messaggio nell'app reale. |
| 6. Voce/Gemini Live | DA VALIDARE LIVE | Servono sessione, microfono e output audio; non eseguire script che inviano credenziali. |
| 7. Tool `system_status`/GPU | PARZIALE L2 | Chiamata locale a `get_system_status()` ha restituito `gpu_percent=24.0` al campione. Non prova dispatch Gemini, pronuncia né accuratezza oltre quel campione. |
| 8. Stato finale | NON VALIDATO | Rimane così finché i criteri live non sono registrati. |

Checklist prova manuale:

- [ ] Avvia il server fixture locale con `python tests\serve_fixtures.py` dalla root Jarvis; annota l'indirizzo e la porta stampati.
- [ ] Dì «Rispondi: test voce completato»; atteso: connessione Live e risposta udibile. Riporta se compare `JARVIS online`; non inviare né mostrare chiavi.
- [ ] Dì «Apri http://127.0.0.1:<porta>/page_simple.html»; atteso: pagina integrata col titolo «Pagina semplice di test». Usa il link «Leggi pagina successiva», poi i pulsanti UI Indietro e Avanti; atteso: seconda pagina e ritorno/avanzamento corretti. Il solo HTTP 200 della fixture è già verificato a L2.
- [ ] Dì «Clicca il link Leggi pagina successiva»; atteso: navigazione alla seconda fixture. Su `snake.html`, dì «Premi la freccia destra»; atteso: variazione osservabile della direzione/posizione. Prova «Premi Tab»; atteso: rifiuto perché Tab non è nella whitelist.
- [ ] Apri `page_long.html` e dì «Leggi ad alta voce la pagina»; dì poi «Smetti di leggere»; atteso: voce locale, stop tempestivo, GUI reattiva e nessuna sovrapposizione audio udibile.
- [ ] Apri `page_empty.html` e dì «Leggi ad alta voce la pagina»; atteso: «The active page contains no readable text» (o messaggio italiano equivalente), nessun crash.
- [ ] Dì «Qual è il carico della GPU?»; atteso: valore corrente letto da NVML oppure indisponibilità esplicita. Il probe locale ha rilevato 24.0% in un singolo campione; verifica che Gemini invochi lo strumento e riferisca il dato senza inventarlo.
- [ ] Interrompi il server fixture con Ctrl+C dopo le prove e invia gli esiti per ciascuna voce; non passare alla meccanica 001 prima del recap di 000.

## 10. Recap (F8)

**F8 non completata.** F7 attende gli esiti live dell'utente; registro e commit finale restano aperti fino alla convalida o alla chiusura motivata della meccanica.

### RECAP — IMPL-000 Validazione live M1-M4

- Esito: IN CORSO.
- Cosa è stato fatto: completati F1–F4 sul checkout reale; aggiornata la procedura ai percorsi reali; eseguiti i comandi di test richiesti e preparata la checklist live.
- File creati/modificati: `docs/impl/ROADMAP.md` (copia byte-identica della guida fornita), `docs/impl/IMPL-000-validazione-live-base.md`.
- Verifica: pytest 115 pass/1.36s; compile mirato PASS; compileall . FALLITO nel test Mediapipe sotto `.venv`; unittest 0 test, exit 5.
- Convalida: 0 OK live · 6 verifiche UI/audio/Gemini/dispatch GPU DA VALIDARE LIVE · 2 verifiche locali L2 parziali (fixture HTTP e campione NVML) · 1 gate automatico parziale; meccanica complessiva non validata.
- Debito residuo: prove live di Gemini/audio, browser, interazione, TTS e GPU; scostamento `nvidia-smi`/NVML; compatibilità Python 3.11/3.12; F7 e F8.
- Decisioni da prendere: nessuna ora; le prove live richiedono la sessione e i dispositivi della postazione.
- Prossima meccanica: nessuna finché IMPL-000 non ha un recap conclusivo.

### Recheck di completezza — 2026-10-06

| Fase | Esito del controllo | Stato |
|------|----------------------|-------|
| F1 — Diagnosi | Ricontrollata contro codice e tool registrati; corretta la descrizione del gate audio: la connessione del segnale esiste. | COMPLETATA, con rettifica documentale |
| F2 — Procedura | Step aggiornati a test, fixture/browser, interazione, screen reader e GPU, senza modifiche applicative speculative. | COMPLETATA |
| F3 — Scheda IMPL | File presente in `docs/impl/` con sezioni 1–10 del template. | COMPLETATA |
| F4 — Fattibilità | Rivalutata rispetto a ROADMAP e codice; verdetto GO CON MODIFICHE, gap GPU e runtime dichiarati. | COMPLETATA, GO CON MODIFICHE |
| F5 — Implementazione | Nessuna modifica di codice richiesta dal piano di validazione; non applicabile a questa scheda. | N/A |
| F6 — Verifica | Questo turno: pytest 115 pass; compile mirato PASS; compileall . fallisce nel test Mediapipe dentro `.venv`; unittest 0 test. | PARZIALE |
| F7 — Convalida | Fixture HTTP L2 parziale (cinque GET 200) e campione NVML L2 24.0%; GUI, microfono, audio, Gemini e dispatch vocale GPU non provati. | PARZIALE, APERTA |
| F8 — Recap/registro/commit | È presente solo un recap provvisorio nella scheda; registro master e commit finale non aggiornati. | APERTA |

**Esito del recheck:** F1–F4 sono concluse e F6 è stata rieseguita. La prova locale ha confermato a L2 le risposte HTTP di tutte le fixture e un singolo campione NVML. I limiti del compileall completo e di unittest sono registrati. Non tutto il ciclo è completo. `ROADMAP.md` resta copia identica alla fonte; codice applicativo invariato. IMPL-000 resta aperta per le prove GUI/audio/Gemini e F8; non passare alla 001.
