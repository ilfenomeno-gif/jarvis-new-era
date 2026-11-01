# JARVIS ULTIMATE — FILE IMPLEMENTATIVO MASTER

Repo: https://github.com/ilfenomeno-gif/jarvis-ultimate
Lingua di lavoro: **italiano** (commenti, docstring, recap, commit).

Questo file contiene:

1. Regole ferree
2. Il **ciclo obbligatorio** da ripetere per OGNI meccanica e OGNI step
3. Template del file di implementazione (`IMPL-XXX`)
4. Template del recap
5. Registro di avanzamento
6. Backlog ordinato (dal brainstorming)
7. **PROMPT MASTER** da incollare all'agente
8. Mini-prompt parametrico per la singola meccanica

---

## 1. REGOLE FERREE

1. **Mai costruire su fondamenta non verificate.** Una meccanica è "chiusa" solo dopo convalida, non dopo scrittura del codice.
2. **Prima leggi, poi decidi.** Ogni diagnosi parte dal codice reale del repo, non dal brainstorming né dal README. Il README dichiara già memoria lunga, meteo, controllo YouTube, volume, Wi-Fi, ricerca file, OCR, undo e plugin: molte voci del brainstorming potrebbero esistere in parte. Va verificato, non assunto.
3. **Estendi, non duplicare.** Se esiste un modulo (`actions/`, `core/`, `memory/`, `plugins/`), si estende. Nuovo codice nel core solo se non c'è alternativa; il resto va come plugin (`plugins/_template.py`).
4. **Guardrail intoccabili.** Whitelist comandi/path, conferma umana per azioni irreversibili (spegnimento, riavvio, Wi-Fi, kill process), undo dove possibile. Nessuna nuova azione distruttiva senza conferma.
5. **Un branch per meccanica**, mai push né merge su `main` senza ordine esplicito.
6. **Nessun segreto nel repo** (`config/api_keys.json`, token, certificati, `memory/long_term.json` restano fuori da Git).
7. **Una meccanica alla volta.** Non si apre la successiva finché la precedente non ha il recap firmato.
8. **Onestà dei risultati.** Cose non testabili senza GUI/audio/driver reali vanno marcate `DA VALIDARE LIVE`, mai `OK`.
9. **Niente trappole** (dal brainstorming): niente trading/esecuzione ordini, niente OAuth fragili all'inizio, niente smart home senza dispositivi, niente troppi plugin insieme.

---

## 2. IL CICLO OBBLIGATORIO (per ogni meccanica e ogni step)

```
F1 Analisi e diagnosi della meccanica
        ↓
F2 Elaborazione della procedura
        ↓
F3 Creazione del file di implementazione (IMPL-XXX.md)
        ↓
F4 Analisi e diagnosi del file di implementazione  ──► GATE: fattibile?
        ↓ sì                                              ↓ no → torna a F2/F3
F5 Implementazione
        ↓
F6 Verifica (tecnica, automatica)
        ↓
F7 Convalida (funzionale, live, criteri di accettazione)
        ↓
F8 Recap + commit + aggiornamento registro
        ↓
   prossima meccanica → F1
```

Ogni fase ha un **output scritto** e una **uscita (gate)**. Non si passa oltre senza.

### F1 — Analisi e diagnosi della meccanica
**Cosa fai**
- Leggi i file reali coinvolti (punto d'ingresso, `actions/`, `core/`, `plugins/`, `tests/`, `PIANO_TECNICO_JARVIS.md`).
- Rispondi per iscritto a:
  - Cosa esiste già per questa meccanica? (file, funzioni, tool registrati in Gemini)
  - Cosa funziona, cosa è solo implementato, cosa manca?
  - Da cosa dipende (librerie, API, OS, permessi, hardware)?
  - Cosa può rompere (core, guardrail, latenza, loop audio)?
  - Rischi di sicurezza/privacy?
  - Stima onesta dello sforzo.
- Classifica lo stato: `ASSENTE` / `PARZIALE` / `IMPLEMENTATA-NON-VALIDATA` / `VALIDATA`.

**Output:** sezione "Diagnosi" dell'IMPL.
**Gate:** se lo stato è `VALIDATA`, la meccanica si salta; se `IMPLEMENTATA-NON-VALIDATA`, si salta a F6 (solo validazione).

### F2 — Elaborazione della procedura
- Scegli l'approccio (plugin vs azione vs core) con motivazione.
- Scomponi in step piccoli, ciascuno verificabile da solo.
- Per ogni step definisci: file toccati, funzione/tool nuovo, dipendenze nuove, test previsto.
- Definisci i **criteri di accettazione** (osservabili: "dico X, Jarvis fa Y, vedo Z nel log").
- Prevedi il **piano di rollback**.

**Output:** sezione "Procedura" dell'IMPL.

### F3 — Creazione del file di implementazione
- Crea `docs/impl/IMPL-XXX-nome-meccanica.md` dal template (sez. 3).
- Deve essere così completo che un altro agente potrebbe implementarlo senza fare domande.

**Output:** il file IMPL.

### F4 — Analisi e diagnosi del file di implementazione (fattibilità)
Rileggi l'IMPL con occhio critico e compila la checklist:

- [ ] I file e le funzioni citati esistono davvero (ho verificato i nomi)?
- [ ] Le dipendenze sono installabili sulla macchina target (Windows 10/11, Python 3.11/3.12)?
- [ ] Gli step sono ordinati senza dipendenze circolari?
- [ ] Nessuno step viola i guardrail o aggira le conferme?
- [ ] Ogni step ha un test o una verifica concreta?
- [ ] I criteri di accettazione sono misurabili?
- [ ] Il rollback è reale (branch/commit separato)?
- [ ] Lo sforzo stimato è coerente con la complessità?
- [ ] Impatto sul tempo di risposta vocale valutato?
- [ ] Cosa non è testabile senza GUI/audio reale è dichiarato?

**Verdetto (obbligatorio):**
- `GO` → si implementa.
- `GO CON MODIFICHE` → correggi l'IMPL, riesegui F4 una volta.
- `NO-GO` → motivazione, torna a F2 o proponi alternativa/rinvio.

### F5 — Implementazione
- Branch dedicato: `feat/<nome-meccanica>`.
- Un commit per step, messaggio in italiano e riferimento `IMPL-XXX step N`.
- Segui lo stile del codice esistente; type hint e docstring brevi.
- Nessuna modifica fuori dal perimetro dell'IMPL. Se serve, aggiorna prima l'IMPL e rifai F4 per la parte cambiata.

### F6 — Verifica (tecnica, automatica)
Esegui sempre:
```
python -m compileall .
python -m unittest discover -s tests -v
```
- Aggiungi test in `tests/` per ogni nuova funzione/contratto.
- Riporta l'output reale (pass/fail, numeri). Niente "dovrebbe funzionare".
- Se un test fallisce: massimo **2 cicli** correzione→riverifica; poi fermati e riferisci.

### F7 — Convalida (funzionale)
- Esegui i criteri di accettazione dell'IMPL uno per uno.
- Per ognuno segna: `OK` / `FALLITO` / `DA VALIDARE LIVE` (serve microfono, GUI, GPU, rete reale).
- Fornisci all'utente la **checklist di prova manuale** per i punti non automatizzabili, con frasi esatte da dire a Jarvis e risultato atteso.
- Verifica che i guardrail e le conferme funzionino ancora (test di regressione sui contratti esistenti).

### F8 — Recap, commit, registro
- Scrivi il recap (template sez. 4).
- Aggiorna il registro (sez. 5).
- Commit finale della meccanica (sul branch, nessun push su `main`).
- Dichiara esplicitamente la prossima meccanica e chiedi via libera solo se c'è un NO-GO, un fallimento non risolto o una decisione dell'utente. Altrimenti prosegui con F1 della successiva.

### Regole del loop
- Ordine del backlog: sez. 6, salvo diversa indicazione.
- **Stop obbligatorio e richiesta di decisione** se: NO-GO, 2 cicli di fix falliti, azione che tocca guardrail/segreti, dipendenza a pagamento o con OAuth, ambiguità non risolvibile dal codice.
- A fine di ogni sprint: recap di sprint + elenco `DA VALIDARE LIVE` ancora aperti.

---

## 3. TEMPLATE — `docs/impl/IMPL-XXX-nome.md`

```markdown
# IMPL-XXX — <Nome meccanica>

Data: <AAAA-MM-GG>   Branch: feat/<nome>   Stato: BOZZA | GO | IN CORSO | VERIFICATA | CONVALIDATA | CHIUSA

## 1. Obiettivo
<Una frase: cosa deve poter fare l'utente.>

## 2. Diagnosi (F1)
- Stato attuale: ASSENTE | PARZIALE | IMPLEMENTATA-NON-VALIDATA | VALIDATA
- File esistenti coinvolti: <percorso — ruolo>
- Dipendenze: <librerie / API / OS / hardware>
- Rischi: <core, guardrail, latenza, privacy>
- Sforzo stimato: <ore>

## 3. Procedura (F2)
Approccio: <plugin | azione | core> — motivo: <...>

| Step | Descrizione | File toccati | Test/verifica |
|------|-------------|--------------|---------------|
| 1 | | | |
| 2 | | | |

## 4. Criteri di accettazione
1. Dico "<frase>" → Jarvis <azione> → osservo <risultato>.
2. ...

## 5. Rollback
<Come tornare indietro: revert dei commit, flag di disattivazione, ecc.>

## 6. Diagnosi di fattibilità (F4)
Checklist: <spunte>
Verdetto: GO | GO CON MODIFICHE | NO-GO — <motivazione>

## 7. Log di implementazione (F5)
- Step 1: <commit/hash> — <note>

## 8. Verifica (F6)
- compileall: <esito>
- unittest: <n test, pass/fail>
- Test nuovi: <elenco>

## 9. Convalida (F7)
| Criterio | Esito | Note |
|----------|-------|------|
| 1 | OK / FALLITO / DA VALIDARE LIVE | |

Checklist prova manuale per l'utente:
- [ ] <frase da dire> → atteso: <...>

## 10. Recap (F8)
<vedi template recap>
```

---

## 4. TEMPLATE — RECAP

```markdown
### RECAP — IMPL-XXX <nome>
- Esito: CHIUSA | CHIUSA CON RISERVE | BLOCCATA
- Cosa è stato fatto: <3-5 righe>
- File creati/modificati: <elenco>
- Verifica: compileall <esito> · unittest <n/n>
- Convalida: <n> OK · <n> DA VALIDARE LIVE · <n> FALLITI
- Debito residuo: <cosa resta aperto>
- Decisioni da prendere: <se presenti>
- Prossima meccanica: IMPL-YYY <nome>
```

---

## 5. REGISTRO DI AVANZAMENTO

| ID | Meccanica | Stato iniziale | F4 | Verifica | Convalida | Esito |
|----|-----------|----------------|----|----------|-----------|-------|
| 000 | Validazione live base (voce, browser, interazione web, screen reader, GPU) | IMPL-NON-VALIDATA | | | | |
| 001 | Memoria persistente (fatti, preferenze, ricerca, dimentica) | da diagnosticare | | | | |
| 002 | Screenshot + avvio app | da diagnosticare | | | | |
| 003 | Promemoria, timer, sveglia, note | da diagnosticare | | | | |
| 004 | Meteo + news RSS | da diagnosticare | | | | |
| 005 | Auto-riassunto pagina | da diagnosticare | | | | |
| 006 | YouTube controls | da diagnosticare | | | | |
| 007 | CPU/RAM/disco/processi (estende GPU) | da diagnosticare | | | | |
| 008 | Visione schermo (screenshot → Gemini Vision) | da diagnosticare | | | | |
| 009 | OCR + traduzione screenshot | da diagnosticare | | | | |
| 010 | Cerca file | da diagnosticare | | | | |
| 011 | Wake word | da diagnosticare | | | | |
| 012 | Routine automatiche ("modalità lavoro") | da diagnosticare | | | | |
| 013 | Secondo cervello (diario + ricerca) | da diagnosticare | | | | |
| 014 | Jarvis gioca a Snake | da diagnosticare | | | | |
| 015 | Fallback LLM locale (Ollama) | da diagnosticare | | | | |

---

## 6. BACKLOG ORDINATO

**Sprint 0 — Fondamenta (prima di tutto)**
- 000 Validazione live di voce, browser, interazione web, screen reader, GPU. Fino a che non è chiusa, le feature sopra non si considerano affidabili.

**Sprint 1 — Memoria + sistema base**
- 001 Memoria persistente · 002 Screenshot + avvio app

**Sprint 2 — Produttività**
- 003 Promemoria/timer/note · 004 Meteo/news · 005 Auto-riassunto · 006 YouTube controls

**Sprint 3 — Sistema + visione**
- 007 CPU/RAM/disco · 008 Visione schermo · 009 OCR+traduzione · 010 Cerca file

**Sprint 4 — Wow**
- 011 Wake word · 012 Routine · 013 Secondo cervello · 014 Snake

**Trasversale (quando servono)**
- 015 LLM locale/Ollama, cache, retry, logging strutturato, event bus.

> Nota: dato che il README dichiara già memoria lunga, meteo, YouTube, ricerca file, volume/Wi-Fi, OCR e screenshot-vision, per molte voci la F1 potrebbe concludere `PARZIALE` o `IMPLEMENTATA-NON-VALIDATA`: in quel caso il lavoro è estendere e validare, non riscrivere.

---

## 7. PROMPT MASTER (da incollare all'agente)

```text
RUOLO
Sei l'ingegnere responsabile di JARVIS Ultimate (Python, Gemini Live API, HUD PyQt6).
Repo: https://github.com/ilfenomeno-gif/jarvis-ultimate
Lavori in italiano: commenti, docstring, commit, recap.

MISSIONE
Portare avanti il backlog del file JARVIS_FILE_IMPLEMENTATIVO_MASTER.md (sezione 6),
una meccanica alla volta, seguendo SEMPRE il ciclo F1→F8 della sezione 2.
Non saltare fasi e non passare alla meccanica successiva senza recap.

REGOLE FERREE
- Prima leggi il codice reale, poi decidi. Non fidarti di README o brainstorming:
  verifica cosa esiste già. Estendi, non duplicare.
- Rispetta i guardrail (whitelist comandi/path, conferme per azioni irreversibili, undo).
  Nessuna nuova azione distruttiva senza conferma umana.
- Un branch per meccanica (feat/<nome>). Mai push o merge su main senza mio ordine.
- Nessun segreto nel repo.
- Non dichiarare "OK" ciò che non puoi provare: usa DA VALIDARE LIVE e dammi la
  checklist di prova manuale.
- Output reali di test, non supposizioni.

CICLO PER OGNI MECCANICA
F1 Analisi e diagnosi della meccanica (stato: ASSENTE / PARZIALE / IMPLEMENTATA-NON-VALIDATA / VALIDATA)
F2 Elaborazione della procedura (step piccoli, file toccati, test, criteri di accettazione, rollback)
F3 Creazione del file docs/impl/IMPL-XXX-nome.md dal template
F4 Analisi e diagnosi del file IMPL: checklist di fattibilità e verdetto GO / GO CON MODIFICHE / NO-GO
F5 Implementazione (solo se GO), un commit per step
F6 Verifica: python -m compileall . e python -m unittest discover -s tests -v + nuovi test
F7 Convalida: criteri di accettazione uno per uno + checklist manuale per i punti live
F8 Recap (template), aggiornamento registro, commit finale, poi passa alla successiva

STOP E DOMANDA a me se: NO-GO, 2 cicli di fix falliti, tocco a guardrail/segreti,
dipendenze a pagamento o OAuth, ambiguità non risolvibile dal codice.
Altrimenti prosegui in loop fino alla fine del backlog.

FORMATO DELLE TUE RISPOSTE
Per ogni meccanica, in ordine: Diagnosi → Procedura → (IMPL creato) → Verdetto F4 →
Implementazione → Verifica (output test) → Convalida (tabella) → Recap.
Sii conciso: niente preamboli, niente ripetizioni.

INIZIA ORA
Esegui la F1 della meccanica 000 (validazione live base di voce, browser,
interazione web, screen reader, GPU).
```

---

## 8. MINI-PROMPT PARAMETRICO (per una singola meccanica)

```text
Applica il ciclo F1→F8 del file JARVIS_FILE_IMPLEMENTATIVO_MASTER.md
alla meccanica: <NOME MECCANICA>.
Obiettivo utente: <cosa deve poter dire/fare>.
Vincoli: <es. solo offline, nessuna dipendenza nuova, solo plugin>.
Fermati dopo il recap e attendi il mio via libera.
```
