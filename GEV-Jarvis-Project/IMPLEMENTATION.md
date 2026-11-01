# JARVIS ULTIMATE — FILE IMPLEMENTATIVO MASTER

Repository: https://github.com/ilfenomeno-gif/jarvis-ultimate
Scopo: trasformare Jarvis in un hub unificato (browser integrato, interazione attiva con pagine/giochi, screen reader, integrazione NVIDIA).

> Questo file è la **fonte di verità** del progetto. L'agente lo legge a ogni inizio ciclo e aggiorna `PROGRESS.md` a ogni fine ciclo.

---

## 0. REGOLE GENERALI (valgono per ogni meccanica)

1. **Mai assumere**: ogni nome di file, classe, metodo citato in questo documento (es. `ui.py`, `plugins/gev_plugin.py`, `QWebEngineView`, `QStackedWidget`) è una *ipotesi* finché non è verificata leggendo il codice reale del repo.
2. **Un ciclo = una meccanica.** Non iniziare la successiva se il ciclo corrente non ha superato la convalida (o non è marcata `BLOCKED`/`NO-GO` con motivo).
3. **Git**: un branch per meccanica (`feat/mNN-nome`), commit piccoli e descrittivi, merge su `main` solo dopo convalida.
4. **Niente azioni distruttive**: non cancellare file, non riscrivere storia git, non toccare credenziali/API key. Le chiavi restano in `.env` e non vengono mai stampate nei log.
5. **Backup logico**: prima di modificare un file esistente, annotare in `PROGRESS.md` cosa viene toccato.
6. **Se qualcosa è ambiguo e bloccante** (es. NVIDIA): marcare la meccanica `BLOCKED`, registrare la domanda in `OPEN_QUESTIONS.md`, e **continuare con la meccanica successiva**. Non fermare l'intero loop.
7. **Stop del loop** solo quando: tutte le meccaniche sono `DONE`, `BLOCKED` o `NO-GO`, oppure si verifica un errore non recuperabile (documentarlo).

---

## 1. PROCEDURA CICLICA (da eseguire per OGNI meccanica e OGNI step)

```
┌──────────────────────────────────────────────────────────────┐
│ STEP 1  ANALISI E DIAGNOSI del progetto/meccanica            │
│ STEP 2  ELABORAZIONE della procedura                         │
│ STEP 3  CREAZIONE del file implementativo della meccanica    │
│ STEP 4  ANALISI E DIAGNOSI del file implementativo (GO/NO-GO)│
│ STEP 5  IMPLEMENTAZIONE                                      │
│ STEP 6  VERIFICA (tecnica)                                   │
│ STEP 7  CONVALIDA (funzionale)                               │
│ STEP 8  RECAP                                                │
│ STEP 9  → prossima meccanica (torna a STEP 1)                │
└──────────────────────────────────────────────────────────────┘
```

### STEP 1 — Analisi e diagnosi
- Leggere la struttura reale del repo (`tree`, entry point, UI, plugin, gestione azioni vocali, integrazione Gemini).
- Individuare dove la meccanica si innesta: file, classi, segnali/slot, registro delle azioni.
- Elencare: dipendenze già presenti / mancanti, versione Python, versione PyQt/PySide, OS.
- Diagnosi dei rischi: conflitti con codice esistente, thread-safety Qt, import circolari, performance.
- **Output**: sezione "Diagnosi" nel file implementativo della meccanica.

### STEP 2 — Elaborazione procedura
- Scomporre la meccanica in sotto-passi atomici e ordinati.
- Per ogni sotto-passo: file coinvolto, modifica prevista, criterio di successo.
- Definire il piano di test (manuale + automatico) *prima* di scrivere codice.
- **Output**: sezione "Procedura" nel file implementativo.

### STEP 3 — Creazione file implementativo
- Creare `docs/impl/MNN-nome.md` con il template della sezione 5 di questo documento.
- Deve contenere: obiettivo, diagnosi, procedura, modifiche per file, test plan, rollback.

### STEP 4 — Analisi e diagnosi del file implementativo
Checklist di fattibilità (tutte devono essere SÌ per procedere):
- [ ] Ogni file/classe/metodo citato esiste davvero (o è marcato "da creare")?
- [ ] Le dipendenze sono installabili sull'ambiente corrente?
- [ ] Nessun conflitto con meccaniche già `DONE`?
- [ ] Il test plan è eseguibile senza risorse che non ho?
- [ ] Il rollback è definito?

Esito: **GO** → STEP 5. **NO-GO** → correggere il file implementativo e ripetere STEP 4 (max 3 tentativi, poi `BLOCKED` con motivo).

### STEP 5 — Implementazione
- Seguire la procedura sotto-passo per sotto-passo.
- Dopo ogni sotto-passo: eseguire import-check (`python -c "import ..."`) e un avvio rapido dell'app.
- Commit dopo ogni sotto-passo funzionante.

### STEP 6 — Verifica (tecnica)
- Lint/sintassi: `python -m compileall .` (+ `ruff`/`flake8` se presenti).
- Test automatici esistenti + nuovi test per la meccanica (`pytest`).
- Avvio dell'app senza errori né warning nuovi in console.
- Nessuna regressione sulle funzioni già esistenti (GEV incluso).

### STEP 7 — Convalida (funzionale)
- Eseguire gli scenari d'uso reali della sezione "Criteri di accettazione" della meccanica.
- Ogni criterio: `PASS` / `FAIL` con evidenza (output, log, descrizione).
- Se un criterio è `FAIL` → tornare a STEP 5 (max 3 iterazioni), poi `BLOCKED`.

### STEP 8 — Recap
Aggiornare `PROGRESS.md` con: cosa è stato fatto, file toccati, test eseguiti, esito convalida, problemi aperti, prossima meccanica. Poi mostrare il recap a schermo e passare alla meccanica successiva.

---

## 2. ORDINE DELLE MECCANICHE

| ID  | Meccanica                                   | Dipende da | Stato iniziale |
|-----|---------------------------------------------|------------|----------------|
| M0  | Discovery e baseline del repo               | —          | TODO           |
| M1  | Browser integrato (YouTube, siti web)       | M0         | TODO           |
| M2  | Interazione attiva (click, tasti, giochi)   | M1         | TODO           |
| M3  | Screen reader personale (lettura pagina)    | M1         | TODO           |
| M4  | Integrazione NVIDIA                         | M0         | BLOCKED (serve scelta utente) |

---

## 3. SPECIFICA DELLE MECCANICHE

### M0 — Discovery e baseline
**Obiettivo**: capire il repo reale prima di toccare qualsiasi cosa.
- Produrre `docs/REPO_MAP.md`: albero cartelle, entry point, dove vive la UI, dove si registrano le azioni vocali/plugin, come Gemini invoca le funzioni, versione Qt.
- Verificare che l'app si avvii *prima* di qualsiasi modifica (baseline). Registrare eventuali errori preesistenti: non sono responsabilità delle meccaniche successive.
- Confermare/smentire le ipotesi: `ui.py`, `plugins/gev_plugin.py`, `QWebEngineView`, `QStackedWidget`.
- **Accettazione**: `REPO_MAP.md` esiste e ogni ipotesi è marcata CONFERMATA / SMENTITA (con percorso reale).

### M1 — Browser integrato
**Obiettivo**: aprire qualsiasi URL in una vista dentro Jarvis, con avanti/indietro/chiudi.
**Procedura indicativa** (da adattare dopo M0):
1. UI: nuova pagina nel contenitore centrale (es. `QStackedWidget`) con `QWebEngineView`, metodo `open_url_in_webview(url)`, navigazione avanti/indietro/ricarica/chiudi.
2. Normalizzazione URL: aggiungere `https://` se manca schema; rifiutare schemi diversi da `http`/`https`.
3. Plugin/azione vocale `open_website(url)` + mappatura nomi comuni ("YouTube" → `https://www.youtube.com`).
4. Comunicazione plugin → UI tramite segnali Qt (mai chiamare widget da thread non-GUI).
5. Registrare l'azione nelle function declarations di Gemini.

**Accettazione**:
- [ ] "Apri YouTube" carica youtube.com dentro Jarvis.
- [ ] Un URL arbitrario (es. `example.com`) si apre.
- [ ] Indietro/avanti/chiudi funzionano e si torna alla vista precedente.
- [ ] Schema non valido (`file://`, `javascript:`) viene rifiutato.
- [ ] Nessuna regressione su GEV.

### M2 — Interazione attiva (click, link, giochi)
**Obiettivo**: simulare click e tasti nella pagina attiva (es. frecce per Snake).
1. UI: `send_keys_to_webview(key)` e `click_element_in_webview(...)` via `runJavaScript()`.
2. Tasti: dispatch di `KeyboardEvent` (`keydown` + `keyup`) con `key`, `code`, `keyCode` corretti; fallback con `QTest.keyClick`/`QKeyEvent` sul widget se la pagina ignora gli eventi sintetici (molti giochi non accettano eventi `isTrusted=false`).
3. Click per testo del link: ricerca nel DOM per testo visibile; i parametri vanno **passati come JSON escaped** (`json.dumps`) dentro lo script, **mai concatenati** (evita injection).
4. Azioni vocali: `press_key(key)`, `click_link(link_text)`.
5. Whitelist dei nomi tasto accettati (frecce, spazio, invio, lettere, ESC).
6. Focus: assicurare che la web view abbia il focus prima di inviare tasti.

**Accettazione**:
- [ ] "Premi freccia su" muove lo snake in un gioco Snake web di test.
- [ ] "Clicca su <testo link>" apre il link corretto in una pagina di test.
- [ ] Input con virgolette/apici/caratteri speciali non rompe lo script.
- [ ] Tasto non in whitelist → errore gestito, nessun crash.

### M3 — Screen reader personale
**Obiettivo**: Jarvis legge ad alta voce il contenuto della pagina attiva.
1. UI: `read_page_aloud()` estrae testo con `runJavaScript("document.body.innerText")` (callback asincrona).
2. TTS: iniziare con `pyttsx3` (offline). Eseguirlo **in un thread/worker separato** per non bloccare la GUI; prevedere stop/pausa ("smetti di leggere").
3. Pulizia testo: rimuovere spazi multipli, limitare la lunghezza per chunk, segmentare per frasi.
4. Azioni vocali: `read_page`, `stop_reading`.
5. (Opzionale, dopo convalida) lettura solo della selezione o del titolo/paragrafo corrente; alternativa `gTTS` se serve qualità superiore.

**Accettazione**:
- [ ] "Leggi la pagina" avvia la lettura, la GUI resta reattiva.
- [ ] "Smetti di leggere" interrompe entro pochi secondi.
- [ ] Pagina vuota o con testo lunghissimo non causa crash.
- [ ] Nessun conflitto con il TTS già usato da Jarvis (se presente).

### M4 — Integrazione NVIDIA  ⛔ BLOCKED
Serve la scelta dell'utente. **L'agente NON implementa nulla finché `OPEN_QUESTIONS.md` non contiene una risposta.**
Opzioni da proporre all'utente:
- **A) G-Assist**: plugin ponte tra Jarvis e NVIDIA G-Assist (richiede G-Assist installato e configurato).
- **B) Moonlight / game streaming**: Jarvis avvia Moonlight e seleziona un gioco. *Nota*: NVIDIA GameStream è stato dismesso; il lato server oggi si fa tipicamente con Sunshine. Da verificare durante la diagnosi.
- **C) Altro** (overlay, registrazione, metriche prestazioni): da specificare.

Quando arriva la risposta: eseguire il ciclo completo (STEP 1–8) come per le altre meccaniche.

---

## 4. FILE DI SUPPORTO DA CREARE (M0)

| File | Contenuto |
|------|-----------|
| `PROGRESS.md` | Stato per meccanica, ultimo recap, prossimi passi |
| `OPEN_QUESTIONS.md` | Domande bloccanti per l'utente (es. NVIDIA) |
| `docs/REPO_MAP.md` | Mappa del repo reale |
| `docs/impl/MNN-nome.md` | File implementativo di ogni meccanica |

Formato `PROGRESS.md`:
```
## MNN — Nome
Stato: TODO | IN_PROGRESS | DONE | BLOCKED | NO-GO
Branch: feat/mNN-nome
File toccati: ...
Verifica: PASS/FAIL (dettagli)
Convalida: PASS/FAIL (criteri)
Problemi aperti: ...
Recap: ...
```

---

## 5. TEMPLATE `docs/impl/MNN-nome.md`

```
# MNN — Nome meccanica
## Obiettivo
## 1. Diagnosi (stato reale del repo, rischi, dipendenze)
## 2. Procedura (sotto-passi atomici: file → modifica → criterio di successo)
## 3. Modifiche per file (elenco preciso)
## 4. Test plan (automatici + manuali)
## 5. Criteri di accettazione (checklist PASS/FAIL)
## 6. Analisi di fattibilità del presente file (checklist GO/NO-GO + esito)
## 7. Rollback (come tornare indietro)
## 8. Registro esecuzione (data, esito verifica, esito convalida)
## 9. Recap finale
```

---

## 6. DEFINIZIONE DI "FATTO"

Una meccanica è `DONE` solo se: il file implementativo esiste ed è GO, il codice è committato sul branch, verifica = PASS, convalida = PASS su tutti i criteri, `PROGRESS.md` è aggiornato e il recap è stato mostrato.
