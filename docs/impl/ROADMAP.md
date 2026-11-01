# JARVIS ULTIMATE — FILE IMPLEMENTATIVO PER VS CODE

Repo: https://github.com/ilfenomeno-gif/jarvis-ultimate
Origine: brainstorming "Jarvis al massimo potenziale" (4 sprint, 15 meccaniche).
Lingua di lavoro: **italiano** (commenti, docstring, commit, recap).

## COME USARLO IN VS CODE

1. Copia questo file nel repo come `docs/impl/ROADMAP.md`.
2. (Opzionale) Copia la sezione 2 in `.github/copilot-instructions.md` (o `CLAUDE.md`) così l'agente la legge a ogni sessione.
3. Apri la chat agente di VS Code (Copilot Agent, Claude Code o simili) e incolla il **PROMPT AGENTE** della sezione 8.
4. L'agente lavora una meccanica alla volta (sezione 4) e tiene aggiornato il registro (sezione 3).

Struttura del repo nota dal README: `main.py`, `ui.py`, `plugin_manager.py`, `core/` (audio, prompt, memoria, guardrail, conferme, undo, `accessibility.py`), `actions/`, `plugins/` (`_template.py`), `memory/` (`long_term.json`), `dashboard/`, `tests/` (`test_automation_contracts.py`), `docs/`. Tutto il resto va verificato leggendo il codice.

---

## 1. REGOLE FERREE

1. **Validare prima di aggiungere.** Nessuna meccanica nuova finché la 000 (validazione live) non è chiusa o esplicitamente scavalcata da me.
2. **Leggi il codice reale prima di decidere.** Il brainstorming è un'idea, il README dichiara già memoria lunga, meteo, YouTube, ricerca file, volume/luminosità/Wi-Fi, OCR, undo e plugin: molte voci potrebbero esistere in parte. **Estendi, non duplicare.** Esempio: il brainstorming propone `memory/facts.json`, ma il repo ha già `memory/long_term.json`: si estende quello.
3. **Guardrail intoccabili:** whitelist comandi/path, conferma umana per azioni irreversibili (spegnimento, riavvio, Wi-Fi, kill process), undo dove possibile.
4. **Un branch per meccanica** (`feat/<nome>`), un commit per step. Mai push/merge su `main` senza mio ordine.
5. **Nessun segreto nel repo** (`config/api_keys.json`, token, certificati, `memory/long_term.json`, log).
6. **Onestà:** ciò che richiede microfono/GUI/GPU/rete reali è `DA VALIDARE LIVE`, mai `OK`. Riporta output reali dei test.
7. **Trappole da evitare:** troppi plugin insieme (meglio pochi e solidi), OAuth fragili (Gmail/Drive) all'inizio, smart home senza dispositivi, trading/ordini (mai), OCR avanzato con Tesseract (preferire Gemini Vision), multi-utente.
8. **Privacy by default:** tutto ciò che registra (diario, screenshot, webcam, clipboard) è **opt-in**, locale, cancellabile con comando vocale, escluso da Git.

---

## 2. CICLO OBBLIGATORIO (per ogni meccanica)

| Fase | Cosa si fa | Uscita (gate) |
|------|-----------|---------------|
| F1 Diagnosi | Leggi i file coinvolti. Stato: `ASSENTE` / `PARZIALE` / `IMPL-NON-VALIDATA` / `VALIDATA`. Dipendenze, rischi, sforzo | Se `VALIDATA` si salta; se `IMPL-NON-VALIDATA` si va a F6 |
| F2 Procedura | Approccio (plugin/azione/core), step piccoli, file toccati, test, criteri di accettazione, rollback | Procedura scritta |
| F3 File IMPL | Crea `docs/impl/IMPL-XXX-nome.md` (template sez. 5) usando la specifica della sez. 6 come base | File creato |
| F4 Fattibilità | Checklist: file/funzioni esistono? dipendenze installabili su Win10/11 + Python 3.11/3.12? nessuna violazione guardrail? ogni step testabile? criteri misurabili? rollback reale? impatto sulla latenza vocale? | Verdetto `GO` / `GO CON MODIFICHE` (una sola revisione) / `NO-GO` |
| F5 Implementazione | Solo se GO. Branch dedicato, un commit per step (`IMPL-XXX step N: ...`) | Codice scritto |
| F6 Verifica | `python -m compileall .` + `python -m unittest discover -s tests -v` + nuovi test. Max 2 cicli di fix | Output reali |
| F7 Convalida | Criteri di accettazione uno a uno: `OK` / `FALLITO` / `DA VALIDARE LIVE` + checklist di prova manuale per me (frasi esatte da dire, risultato atteso) | Tabella esiti |
| F8 Recap | Template sez. 5, aggiorna registro, commit finale, passa alla successiva | Recap |

**Stop e domanda a me se:** NO-GO, 2 cicli di fix falliti, tocco a guardrail/segreti, dipendenza a pagamento o OAuth, ambiguità non risolvibile dal codice. Altrimenti prosegui in loop fino a fine sprint.

---

## 3. REGISTRO DI AVANZAMENTO

| ID | Meccanica | Sprint | Sforzo | Stato iniziale | F4 | Verifica | Convalida | Esito |
|----|-----------|--------|--------|----------------|----|----------|-----------|-------|
| 000 | Validazione live M1-M4 (voce, browser, interazione web, screen reader, GPU) | 0 | – | IMPL-NON-VALIDATA | | | | |
| 001 | Memoria persistente | 1 | 1-3h | da diagnosticare | | | | |
| 002 | Screenshot + avvia app | 1 | 1h | da diagnosticare | | | | |
| 003 | Promemoria + timer + sveglia + note/to-do | 2 | 2-3h | da diagnosticare | | | | |
| 004 | Meteo + news RSS | 2 | 1-2h | da diagnosticare | | | | |
| 005 | Auto-riassunto pagina | 2 | 30 min | da diagnosticare | | | | |
| 006 | YouTube controls | 2 | 2h | da diagnosticare | | | | |
| 007 | CPU/RAM/disco/processi (estende GPU) | 3 | 2-3h | da diagnosticare | | | | |
| 008 | Visione schermo (screenshot → Gemini Vision) | 3 | 2h | da diagnosticare | | | | |
| 009 | OCR + traduzione screenshot | 3 | 3h | da diagnosticare | | | | |
| 010 | Cerca file | 3 | 2h | da diagnosticare | | | | |
| 011 | Wake word | 4 | 4h | da diagnosticare | | | | |
| 012 | Routine automatiche | 4 | 3h | da diagnosticare | | | | |
| 013 | Secondo cervello (diario + ricerca) | 4 | 4h | da diagnosticare | | | | |
| 014 | Jarvis gioca a Snake | 4 | 6h | da diagnosticare | | | | |

Ordine suggerito di esecuzione: 000 → 001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010 → 011 → 012 → 013 → 014. Dipendenze: 008 serve a 009 e 014; 003 serve a 012; 001 serve a 013; 007 alimenta i trigger di sistema di 003.

Trasversali, solo quando servono (non nel loop principale): LLM locale Ollama + fallback multi-modello, cache risposte, retry, rate limiting, logging strutturato, event bus, sandbox plugin.

---

## 4. SPECIFICHE PER MECCANICA

Formato: obiettivo · da verificare in F1 · approccio · step · criteri di accettazione · test · attenzione. Gli step sono una bozza: la F2 li rifinisce sul codice reale.

### 000 — Validazione live M1-M4 (Sprint 0)
- **Obiettivo:** portare a `VALIDATA` ciò che oggi è solo "implementato": voce end-to-end, browser (apri URL, indietro/avanti), interazione web (click, tasti), screen reader (pyttsx3), GPU (`nvidia-smi` read-only).
- **F1:** dove sono i tool registrati su Gemini; quali hanno test; cosa dipende da GUI/audio reale.
- **Step:** 1) per ciascuna area scrivi una checklist di prova manuale con frasi esatte; 2) aggiungi test automatici dove possibile (contratti dei tool, mock di `nvidia-smi`, parsing); 3) elenca i bug trovati e correggi uno alla volta; 4) aggiorna la tabella "Fotografia attuale" con lo stato reale.
- **Criteri:** ogni area ha esito `OK` / `FALLITO` / `DA VALIDARE LIVE` motivato; nessun `OK` senza prova.
- **Attenzione:** questa meccanica richiede me davanti al PC: l'agente prepara le checklist e raccoglie i miei esiti.

### 001 — Memoria persistente
- **Obiettivo:** "ricordati che mia sorella si chiama Anna", "cosa ti avevo detto su Mario?", "dimentica che…", preferenze (caffè amaro, lavoro di notte), memoria conversazionale.
- **F1:** cosa fa già `memory/` e `memory/long_term.json` (struttura, indicizzazione, come viene iniettata nel prompt a inizio sessione, `core/prompts`).
- **Approccio:** estendere la memoria esistente; tool `remember(key, value)`, `recall(query)`, `forget(query)`; caricamento dei fatti all'avvio della sessione Gemini; riassunto conversazione del giorno in `memory/conversations/AAAA-MM-GG.json` (opzionale, dietro flag).
- **Step:** 1) schema dati (fatto, categoria, timestamp, fonte); 2) tool remember/recall/forget con conferma su forget; 3) iniezione fatti nel prompt di sessione con limite di dimensione; 4) ricerca per parola chiave (vettoriale rimandata); 5) test.
- **Criteri:** dico "ricordati che…" → fatto salvato; riavvio Jarvis → "cosa sai di…?" risponde; "dimentica…" → rimosso e non più richiamato.
- **Test:** CRUD sul file di memoria, ricerca, rimozione, file corrotto/vuoto gestito, nessun fatto nei log.
- **Attenzione:** nessun dato sensibile nei log; memoria esclusa da Git; `forget` rimuove davvero la riga.

### 002 — Screenshot + avvia app
- **Obiettivo:** "fai uno screenshot", "apri Steam / Discord / VS Code".
- **F1:** esistono già screenshot (OCR/visione schermo) e avvio app/Steam/Epic in `actions/`?
- **Approccio:** screenshot con `PIL.ImageGrab` salvato in cartella configurata; avvio app tramite **whitelist** di nomi→percorsi in `config/`.
- **Step:** 1) tool `take_screenshot(region?)` → file in `Pictures/Jarvis`; 2) tool `launch_app(name)` con whitelist e alias; 3) risposta vocale con esito; 4) test.
- **Criteri:** screenshot creato e percorso comunicato; app in whitelist si avvia; app fuori whitelist rifiutata.
- **Test:** whitelist (ammessa/negata), percorso di salvataggio, nome file univoco.
- **Attenzione:** nessun avvio di eseguibili arbitrari; passare dai guardrail.

### 003 — Promemoria, timer, sveglia, note/to-do
- **Obiettivo:** "ricordami alle 15 di…", "timer 10 minuti", "svegliami alle 7", "annota: comprare latte", "aggiungi 'chiamare Mario' alla lista".
- **F1:** esiste uno scheduler? come parla Jarvis in modo proattivo (si può far parlare senza input utente?).
- **Approccio:** `APScheduler` in un modulo `core/triggers.py` (o plugin); persistenza su file così i promemoria sopravvivono al riavvio; notifica vocale + notifica HUD. Note/to-do in file locale.
- **Step:** 1) scheduler con persistenza; 2) tool `set_reminder`, `set_timer`, `set_alarm`, `list_reminders`, `cancel_reminder`; 3) notifica vocale proattiva (verifica compatibilità con il ciclo Gemini Live); 4) tool `add_note`, `list_notes`, `add_todo`, `complete_todo`; 5) test con orologio simulato.
- **Criteri:** timer di 1 minuto suona/parla allo scadere; promemoria persiste al riavvio; annota/leggi note funziona.
- **Test:** parsing orari relativi/assoluti, fuso orario Europe/Rome, persistenza, annullamento.
- **Attenzione:** il parlare proattivo non deve interrompere male una conversazione in corso.

### 004 — Meteo + news RSS
- **Obiettivo:** "che tempo fa domani a Roma?", "leggi le notizie di oggi".
- **F1:** il meteo esiste già (README) → quasi certamente `PARZIALE`: verificare previsioni a più giorni.
- **Approccio:** meteo via `wttr.in` o API simile senza chiave; news da feed RSS configurabili in `config/` con `feedparser`.
- **Step:** 1) estendere/validare meteo (oggi/domani/città); 2) tool `get_news(feed?, n)` con titoli + riassunto breve; 3) timeout e gestione offline; 4) test con risposte registrate (mock).
- **Criteri:** meteo di domani per città richiesta; 5 titoli RSS letti; offline → messaggio chiaro.
- **Attenzione:** rispettare i termini dei feed; solo titoli e sintesi, niente copia di articoli interi.

### 005 — Auto-riassunto pagina
- **Obiettivo:** "Jarvis, riassumi" sulla pagina aperta nel browser.
- **F1:** il browser usa Playwright/DOM-first (README): come si estrae il testo della pagina?
- **Approccio:** estrazione testo dal DOM (con limite di lunghezza) → prompt di riassunto a Gemini → risposta vocale breve.
- **Step:** 1) tool `page_text()` pulito (niente script/nav); 2) tool `summarize_page(length)`; 3) gestione pagine lunghe (chunking); 4) test su HTML di esempio.
- **Criteri:** su un articolo aperto, riassunto di 3-5 frasi corretto.
- **Attenzione:** pagine con dati personali: il testo va solo al provider LLM già configurato, mai salvato senza opt-in.

### 006 — YouTube controls
- **Obiettivo:** "pausa", "riprendi", "salta 10 secondi", "velocità 2x", "prossimo video".
- **F1:** il README dice che il controllo YouTube esiste già: verificare quali comandi sono coperti.
- **Approccio:** controllo tramite il browser già in uso (DOM/tasti del player), non nuove dipendenze.
- **Step:** 1) mappa comandi → azione sul player; 2) tool unico `youtube_control(action, value?)`; 3) test del mapping; 4) prova live.
- **Criteri:** ogni comando elencato funziona su un video reale.
- **Attenzione:** l'interfaccia di YouTube cambia: preferire scorciatoie standard del player.

### 007 — CPU/RAM/disco/processi
- **Obiettivo:** "come sta il PC?", "cosa consuma più RAM?", "kill del processo X" (con conferma), temperature, batteria, rete.
- **F1:** com'è fatto il modulo GPU (`nvidia-smi` read-only).
- **Approccio:** `psutil` per CPU/RAM/disco/rete/batteria/processi; temperature dove disponibili (fallback: "non disponibile").
- **Step:** 1) `get_system_status()`; 2) `top_processes(by, n)`; 3) `kill_process(name|pid)` **solo con conferma umana** e blacklist processi di sistema; 4) test con `psutil` simulato.
- **Criteri:** stato sintetico a voce; top 5 processi per RAM; kill rifiutato senza conferma o su processi protetti.
- **Attenzione:** `kill` è azione sensibile: conferma esplicita nell'HUD, blacklist, log.

### 008 — Visione schermo
- **Obiettivo:** "cosa c'è su schermo?", "cosa significa questo errore?", "commenta questo grafico".
- **F1:** il README dichiara già "fallback a visione multimodale": quanto copre?
- **Approccio:** `PIL.ImageGrab` → immagine ridimensionata → Gemini multimodale → risposta vocale.
- **Step:** 1) tool `describe_screen(question?, region?)`; 2) ridimensionamento per costo/latenza; 3) opzione "monitor X"; 4) test con immagini di esempio e mock API.
- **Criteri:** domanda su un errore reale a schermo → spiegazione corretta e pertinente.
- **Attenzione:** l'immagine lascia il PC verso il provider: avviso/consenso nelle impostazioni; niente salvataggio dello screenshot se non richiesto; occhio a finestre con dati sensibili.

### 009 — OCR + traduzione screenshot
- **Obiettivo:** "traduci questo menu", "leggi il testo su schermo".
- **F1:** `core/accessibility.py` ha già OCR locale opzionale (pytesseract).
- **Approccio:** come da brainstorming, **Gemini Vision al posto di OCR avanzato**; Tesseract resta il fallback offline già presente. Riutilizza il tool della 008 con prompt di estrazione/traduzione.
- **Step:** 1) tool `read_screen_text(region?)`; 2) tool `translate_screen(target_lang)`; 3) fallback OCR locale se offline; 4) test.
- **Criteri:** testo in lingua straniera a schermo → traduzione italiana a voce.

### 010 — Cerca file
- **Obiettivo:** "trova contratto.pdf".
- **F1:** la ricerca file esiste già (README, indicizzazione): verificare velocità e percorsi coperti.
- **Approccio:** estendere con ricerca per nome/estensione/data in percorsi consentiti dai guardrail.
- **Step:** 1) tool `find_file(query, folder?)`; 2) risultati limitati (top N) con percorso; 3) test con cartella temporanea.
- **Criteri:** file noto trovato in <3 s; percorsi fuori whitelist non scansionati.
- **Attenzione:** i guardrail sui path valgono anche in lettura.

### 011 — Wake word
- **Obiettivo:** "Jarvis" attiva l'ascolto senza click.
- **F1:** come funziona oggi l'avvio dell'ascolto (`core/` audio, `main.py`).
- **Approccio:** motore wake word **locale** (es. openWakeWord o Porcupine: verificare licenza/chiavi in F4), sempre in ascolto solo del trigger, nessuna registrazione.
- **Step:** 1) valutazione 2 candidati (licenza, CPU, falsi positivi); 2) integrazione nel ciclo audio; 3) soglia configurabile; 4) indicatore HUD "in attesa"; 5) prova live.
- **Criteri:** attivazione affidabile a 1-2 m; falsi positivi accettabili in 30 min di TV accesa (prova live).
- **Attenzione:** privacy del microfono always-on: switch on/off chiaro e visibile; interferenza con TTS di Jarvis (evitare auto-attivazione).

### 012 — Routine automatiche
- **Obiettivo:** "modalità lavoro" → apre VS Code e Slack, imposta volume, silenzia notifiche, timer 2h.
- **Dipende da:** 002, 003, e volume già esistente.
- **Approccio:** routine definite in file di configurazione (JSON/YAML), ognuna una lista di azioni già esistenti, eseguite in sequenza **attraverso gli stessi guardrail**.
- **Step:** 1) formato routine; 2) esecutore con stop al primo errore; 3) tool `run_routine(name)`, `list_routines`; 4) creazione routine a voce (opzionale, dopo); 5) test con azioni simulate.
- **Criteri:** una frase esegue 4+ azioni; se un'azione fallisce, Jarvis dice quale e si ferma.
- **Attenzione:** nessuna azione irreversibile dentro una routine senza conferma.

### 013 — Secondo cervello
- **Obiettivo:** "cosa leggevo ieri?", "quando ho aperto quel sito?".
- **Dipende da:** 001 (+ cronologia browser).
- **Approccio:** diario **opt-in** locale: pagine visitate, comandi, note. Ricerca per parola chiave e data; vettoriale solo dopo, se serve.
- **Step:** 1) schema eventi (tipo, timestamp, testo breve); 2) raccolta da browser e comandi; 3) tool `search_diary(query, date_range)`; 4) comando `cancella diario` per intervallo; 5) retention configurabile; 6) test.
- **Criteri:** "cosa ho aperto ieri?" restituisce l'elenco corretto; cancellazione effettiva.
- **Attenzione:** è la meccanica più delicata per la privacy: opt-in esplicito, file escluso da Git, esclusione domini sensibili (banca, email), nessuna registrazione di password o campi di input.

### 014 — Jarvis gioca a Snake
- **Obiettivo:** loop chiuso screenshot canvas → Gemini Vision → direzione → `press_key`.
- **Dipende da:** 008 e interazione web validata (000).
- **F1 critica:** la latenza di visione (secondi) può essere troppo alta per Snake in tempo reale.
- **Approccio:** partire con Snake **rallentato** o a turni (gioco di test locale con velocità configurabile); per tempo reale valutare estrazione dello stato dal DOM/canvas invece della visione.
- **Step:** 1) mini-gioco di test con velocità regolabile; 2) loop cattura→decisione→tasto con limite di tempo; 3) metriche (punteggio, latenza); 4) confronto visione vs stato strutturato.
- **Criteri:** a velocità ridotta fa almeno N punti senza intervento; log della latenza media.
- **Attenzione:** limitare il loop a una finestra/gioco esplicito; tasto di stop immediato; mai su finestre diverse dal gioco.

---

## 5. TEMPLATE

### 5.1 `docs/impl/IMPL-XXX-nome.md`
```markdown
# IMPL-XXX — <Nome>
Data: <AAAA-MM-GG>  Branch: feat/<nome>  Stato: BOZZA|GO|IN CORSO|VERIFICATA|CONVALIDATA|CHIUSA

## 1. Obiettivo
## 2. Diagnosi (F1)  — stato, file coinvolti, dipendenze, rischi, sforzo
## 3. Procedura (F2) — approccio + tabella step (descrizione | file | test)
## 4. Criteri di accettazione (frasi da dire → risultato atteso)
## 5. Rollback
## 6. Fattibilità (F4) — checklist + verdetto GO|GO CON MODIFICHE|NO-GO
## 7. Log implementazione (F5) — step → commit
## 8. Verifica (F6) — compileall, unittest, test nuovi
## 9. Convalida (F7) — tabella OK|FALLITO|DA VALIDARE LIVE + checklist prova manuale
## 10. Recap (F8)
```

### 5.2 Recap
```markdown
### RECAP — IMPL-XXX <nome>
- Esito: CHIUSA | CHIUSA CON RISERVE | BLOCCATA
- Fatto: <3-5 righe>
- File creati/modificati: <elenco>
- Verifica: compileall <esito> · unittest <n/n>
- Convalida: <n> OK · <n> DA VALIDARE LIVE · <n> FALLITI
- Debito residuo / decisioni per me:
- Prossima meccanica: IMPL-YYY
```

---

## 6. CHECKLIST DI FINE SPRINT

- [ ] Registro (sez. 3) aggiornato
- [ ] `python -m compileall .` e `python -m unittest discover -s tests -v` verdi sull'intero repo
- [ ] Elenco `DA VALIDARE LIVE` ancora aperti consegnato a me
- [ ] README aggiornato con le nuove funzioni (e stato reale: validato / da validare)
- [ ] Nessun segreto o dato personale in Git (`git status`, `.gitignore`)
- [ ] Recap di sprint scritto

---

## 7. ROADMAP IN SPRINT

- **Sprint 0 (prima di tutto):** 000 validazione live.
- **Sprint 1:** 001 memoria, 002 screenshot + avvia app.
- **Sprint 2:** 003 promemoria/timer/note, 004 meteo/news, 005 auto-riassunto, 006 YouTube.
- **Sprint 3:** 007 sistema, 008 visione schermo, 009 OCR/traduzione, 010 cerca file.
- **Sprint 4:** 011 wake word, 012 routine, 013 secondo cervello, 014 Snake.

---

## 8. PROMPT AGENTE (da incollare nella chat di VS Code)

```text
RUOLO
Sei l'ingegnere responsabile di JARVIS Ultimate (Python, Gemini Live API, HUD PyQt6).
Repo: https://github.com/ilfenomeno-gif/jarvis-ultimate
Lavori in italiano: commenti, docstring, commit, recap.

MISSIONE
Esegui il file docs/impl/ROADMAP.md: una meccanica alla volta, nell'ordine del registro
(sezione 3), seguendo SEMPRE il ciclo F1→F8 (sezione 2). Per ogni meccanica crea
docs/impl/IMPL-XXX-nome.md usando la specifica della sezione 4 come base e rifiniscila
sul codice reale.

REGOLE FERREE
- Prima leggi il codice reale, poi decidi. Estendi i moduli esistenti, non duplicare
  (es. usa memory/long_term.json, non creare un secondo archivio di memoria).
- Rispetta i guardrail (whitelist comandi/path, conferme per azioni irreversibili, undo).
- Un branch per meccanica (feat/<nome>), un commit per step. Mai push/merge su main
  senza mio ordine.
- Nessun segreto o dato personale nel repo. Tutto ciò che registra è opt-in e cancellabile.
- Non scrivere "OK" per ciò che non puoi provare: usa DA VALIDARE LIVE e dammi la
  checklist di prova manuale con frasi esatte.
- Riporta output reali di compileall e unittest, mai supposizioni.

LOOP
F1 diagnosi → F2 procedura → F3 file IMPL → F4 fattibilità (GO / GO CON MODIFICHE / NO-GO)
→ F5 implementazione → F6 verifica → F7 convalida → F8 recap + registro → prossima.
Fermati e chiedimi una decisione solo se: NO-GO, 2 cicli di fix falliti, tocco a
guardrail/segreti, dipendenze a pagamento o OAuth, ambiguità non risolvibile dal codice.
Altrimenti prosegui fino alla fine dello sprint.

FORMATO RISPOSTE
Per ogni meccanica: Diagnosi → Procedura → Verdetto F4 → Implementazione → Verifica
(output test) → Convalida (tabella) → Recap. Conciso, niente preamboli.

INIZIA ORA
Esegui la F1 della meccanica 000 (validazione live M1-M4). Prepara le checklist di prova
manuale e aspetta i miei esiti prima di procedere alla 001.
```

### 8.1 Mini-prompt per una sola meccanica
```text
Applica il ciclo F1→F8 di docs/impl/ROADMAP.md alla meccanica <ID e nome>.
Vincoli: <es. solo offline, nessuna nuova dipendenza, solo plugin>.
Fermati dopo il recap e attendi il mio via libera.
```
