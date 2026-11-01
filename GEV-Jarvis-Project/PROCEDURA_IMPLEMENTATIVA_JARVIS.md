# Procedura implementativa JARVIS (ciclo per ogni meccanica e step)

Versione per `github.com/ilfenomeno-gif/jarvis-ultimate` ("JARVIS Mio": Python,
Gemini Live, HUD PyQt6, `actions/`, `core/`, `plugins/`, `dashboard/`, `tests/`).
Sostituisce, per questo progetto, la procedura GEV-Jarvis: stesso ciclo, con
le correzioni emerse dai cicli M0-M4.

Da eseguire **sempre uguale** per ogni meccanica e ogni step, in loop, fino a
coda vuota:

```
[Fase 0 Preflight] → 1 Analisi/Diagnosi → 2 File implementativo
 → 3 Diagnosi di fattibilità → 4 Implementazione → 5 Verifica tecnica
 → 6 Convalida (livelli L1-L4) → 7 Aggiornamento docs/stato → 8 Recap → prossima
```

## 0. Regole fisse

1. **Una meccanica alla volta.** Si passa alla successiva solo dopo il recap
   (fase 8), anche se la convalida è BLOCKED (vedi sezione 2).
2. **Nessuna fase saltata o riordinata.** Ogni fase lascia un artefatto scritto.
3. **Nessuno stato senza prova.** Ogni stato dichiara il livello di prova
   raggiunto (L1-L4). Non si scrive "PASS" per un livello non eseguito.
4. **Decisioni dell'utente non si scelgono al suo posto.** Se serve una scelta
   (esempio: quale "sistema NVIDIA"), l'agente si ferma e chiede. Un'implementazione
   provvisoria è ammessa solo se etichettata `PROVVISORIA` e scartabile.
5. **Segreti.** Mai in URL, mai stampati, mai nei log, mai in commit. Gli script
   che usano chiavi li esegue l'utente, non l'agente; l'output incollato in chat
   deve contenere solo esito/codice HTTP.
6. **Prima di scrivere, leggere i vincoli del repo:** `PIANO_TECNICO_JARVIS.md`,
   cartella `regole e vincoli/`, `soul.md`, `readme.md`. In caso di conflitto con
   questa procedura, vincono i vincoli del repo e si segnala il conflitto.
7. **Non duplicare ciò che esiste.** Prima di creare codice, cercare in
   `actions/`, `core/` e `plugins/` se la capacità c'è già (es. controllo browser
   DOM-first con Playwright, `core/accessibility.py` con OCR, NVDA, `pyttsx3`,
   hotkey). Se esiste: estendere o riusare, non riscrivere.
8. **Nessun push, nessun merge su `main`** senza richiesta esplicita
   dell'utente. Lavoro su branch dedicati (sezione 7).
9. **Non toccare codice non pertinente** (es. non cambiare il modello Gemini
   senza un errore osservato che lo indichi).
10. **Stop dopo 2 rientri consecutivi** sulla stessa fase: riportare blocco,
    ipotesi e opzioni all'utente.

## 1. Vocabolario di stato

| Stato | Significato |
|---|---|
| **DA FARE** | In coda, non iniziata |
| **IMPLEMENTATA – NON CONVALIDATA** | Codice e test automatici ok; convalida live mancante (BLOCKED) |
| **CONVALIDATA Lx** | Prova reale eseguita fino al livello x (vedi sotto) |
| **PASS** | Convalidata almeno al livello richiesto dai criteri di accettazione |
| **PROVVISORIA** | Scelta dell'agente in attesa di decisione utente |
| **SCARTATA** | Rifiutata dall'utente; branch da non unire |
| **NON FATTIBILE** | Diagnosi: impossibile o fuori ambito (con motivazione) |

## 2. Livelli di convalida

Servono a non fermare tutto quando manca un solo servizio (esempio: Gemini).

| Livello | Cosa prova | Richiede Gemini/voce? |
|---|---|---|
| **L1** | Test automatici (suite del repo) + `compileall` + `git diff --check` | No |
| **L2** | Invocazione diretta dello strumento/azione, senza LLM (esempio: funzione GPU che interroga `nvidia-smi`) | No |
| **L3** | Comando testuale dalla UI Jarvis (campo COMMAND INPUT) con effetto visibile | Dipende dal percorso: se passa da Gemini, è bloccato come L4 |
| **L4** | Comando vocale reale col microfono e risposta parlata | Sì |

Regole:
- Ogni criterio di accettazione indica il **livello minimo** richiesto.
- Se L3/L4 sono bloccati da una dipendenza esterna, la meccanica resta
  **IMPLEMENTATA – NON CONVALIDATA**, si registra il blocco e si procede alle
  meccaniche successive **non dipendenti**. I branch non si uniscono.
- L2 si esegue sempre quando possibile: dà evidenza reale anche con Gemini giù.

## 3. Fase 0 — Preflight (prima di ogni sessione o sequenza di cicli)

**Controlli**
1. **Identità del checkout.** Verificare che la cartella locale in uso
   corrisponda al repo atteso: `git remote -v`, branch corrente, `git log -1`.
   (La cartella locale può chiamarsi diversamente dal repo GitHub: annotare la
   corrispondenza una volta e riusarla.)
2. **Working tree.** Pulita, oppure ogni modifica preesistente classificata per
   file/ambito e tenuta fuori dai commit correnti.
3. **Segreti.** `config/api_keys.json` ignorato da Git (`git check-ignore -v`);
   nessuna chiave in staging; nessun file `.env` inatteso.
4. **Baseline test.** Eseguire e registrare comando, conteggi ed errori
   preesistenti. Il README indica `python -m unittest discover -s tests -v`
   e il repo ha `pytest.ini`: usare e annotare **quello effettivamente usato**,
   senza alternare.
5. **Ambiente live.** Jarvis avviabile; Gemini connesso (`JARVIS online`) oppure
   dichiarato non connesso; audio/microfono disponibili; porte/servizi che il
   ciclo richiede (es. GEV su 4173) liberi o già in uso da un solo processo.
6. **Lavoro altrui.** Controllare PR aperte e branch esistenti per non
   sovrapporsi.

**Output:** scheda preflight (branch/HEAD, stato Git, baseline, ambiente).
**Gate:** perimetro chiaro. Prerequisiti live mancanti bloccano solo la fase 6
(a livello L3/L4), non lettura né implementazione.

## 4. Fasi

### Fase 1 — Analisi e diagnosi
- Leggere i vincoli (regola 6) e cercare codice esistente (regola 7).
- Classificare: **A** da validare · **B** da esporre/integrare · **C** da
  progettare · **D** non fattibile.
- Elencare dipendenze: servizi esterni, chiavi, driver, software da installare,
  permessi OS, modello Gemini, altre meccaniche.
- Segnare ogni lacuna come `Da verificare`.
- Se serve una scelta dell'utente: **stop e domanda** (regola 4) prima della fase 2.

**Output:** scheda diagnosi (template 8.1). **Gate:** classe, dipendenze e
lacune scritte.

### Fase 2 — File implementativo
Scrivere `docs/impl/<ID>-<nome>.md` (template 8.2) con obiettivo, fuori
perimetro, interfaccia (nome strumento, parametri, errori), frasi vocali
suggerite, modifiche per file, test, prova per livello (L1-L4), criteri
osservabili, rollback.
**Gate:** ogni modifica indica file e funzione; ogni criterio è passa/non passa
con livello minimo.

### Fase 3 — Diagnosi di fattibilità
Checklist (SÌ / NO / DA VERIFICARE):
1. File e funzioni citati esistono davvero (aperti e letti)?
2. Non duplica codice esistente (regola 7)?
3. Compatibile con i vincoli del repo e con i guardrail (`core/` conferme, undo, validazione percorsi)?
4. Nessuna collisione di nome con strumenti/plugin esistenti?
5. Dipendenze disponibili in locale (pacchetti, driver, permessi, installazioni)?
6. Esiste la prova a ogni livello richiesto? Quali livelli sono realmente raggiungibili ora?
7. Rollback con un revert?
8. Impatto su altre meccaniche e sul ciclo audio/Gemini (es. la lettura vocale non deve sovrapporsi all'audio di Gemini)?
9. Rischi di sicurezza (schemi URL, input da pagine web, comandi di sistema, eventi sintetici)?
10. Commit coerente (un blocco implementativo, vedi sezione 7)?

**Esito:** PROCEDI · RIVEDI PIANO (→ fase 2) · VERIFICA (esegui la verifica e
ripeti) · NON FATTIBILE (→ fase 8).

### Fase 4 — Implementazione
- Solo i file del piano; test insieme al codice.
- Un commit per **blocco implementativo coerente**: `feat(<area>): <blocco> – <sintesi>`.
  Più meccaniche che condividono codice possono stare nello stesso commit,
  ma ciascuna mantiene il proprio ciclo di convalida.
- Prima del commit: `git diff --cached` coerente col piano; nessun segreto.

### Fase 5 — Verifica tecnica (L1)
Test mirati + suite completa + `compileall` + `git diff --check`.
Registrare comando e conteggi. **Gate:** 0 fallimenti. Non modificare un test
per farlo passare senza motivazione scritta.

### Fase 6 — Convalida reale (L2 → L3 → L4)
- Eseguire in ordine i livelli raggiungibili; salvare per ciascuno comando
  usato, esito, condizioni e, se visivo, uno screenshot prima/dopo.
- Provare almeno un caso d'errore (dipendenza assente, input non valido).
- Se un livello è bloccato: registrare **cosa blocca, chi deve agire e come
  sbloccarlo**, assegnare lo stato (sezione 1) e proseguire.

**Se test verdi ma prova reale fallita:** tornare alla fase 1 (la diagnosi era
incompleta).

### Fase 7 — Aggiornamento docs
Aggiornare la tabella di stato delle meccaniche, i limiti noti e il registro
delle decisioni (`OPEN_QUESTIONS.md` o equivalente). Docs e codice devono
dire la stessa cosa.

### Fase 8 — Recap
Compilare il recap (8.4) e riportarlo in chat. Poi prossima voce della coda.
**Fine ciclo:** coda vuota, oppure tutte le voci rimaste sono bloccate da
decisioni/dipendenze esterne → recap finale (8.5).

## 5. Gate speciali

### 5.1 Decisione utente
Quando la fase 1 trova più interpretazioni valide, l'agente propone le opzioni
con costi/requisiti e **aspetta**. Stato della meccanica: `IN ATTESA DI SCELTA`.
Se per non fermare il lavoro prepara una versione, la marca `PROVVISORIA` sul
branch e nel recap; non la include in merge finché l'utente non conferma.

### 5.2 Dipendenza esterna (esempio: Gemini Live non connesso)
Trattare come meccanica a sé (precondizione per L4):
1. Diagnosticare con il **percorso reale** (avviare Jarvis e leggere il log di
   connessione), non solo con una chiamata a un altro modello: una chiamata
   REST a un modello diverso prova la chiave, **non** la sessione Live né il
   modello Live configurato.
2. Separare le cause: chiave/progetto, quota, modello (preview o ritirato),
   rete/firewall, bug websocket nel codice.
3. Nessuna modifica al modello o al codice Live senza un errore osservato.
4. Intanto: proseguire con L1 e L2 delle altre meccaniche.

### 5.3 Segreti e script diagnostici
- Autenticazione con header, mai `?key=` nella URL.
- L'output da incollare contiene solo esito e codice HTTP, mai chiavi o
  stringhe lunghe alfanumeriche.
- L'agente non esegue script che trasmettono credenziali a servizi esterni:
  li prepara, li esegue l'utente.

## 6. Tabella di rientro

| Fase che fallisce | Si torna a | Motivo tipico |
|---|---|---|
| 0 | 0 | Tree non classificata, checkout sbagliato, ambiente non pronto |
| 3 | 2 | Piano incompleto, duplicazione di codice esistente |
| 4 | 2 o 3 | Vincolo scoperto durante il codice |
| 5 | 4 (bug) o 2 (piano errato) | Test rossi |
| 6 | 1 | Test verdi ma comportamento reale diverso |
| 7 | 6 | Stato dichiarato senza prova sufficiente |

Dopo 2 rientri consecutivi sulla stessa fase: stop e domanda all'utente.
Una semplice scelta di granularità dei commit non conta come fallimento.

## 7. Politica Git

- Un branch per blocco implementativo: `feat/m<NN>-<nome>`; branch impilati
  (ciascuno parte dal precedente) solo se dipendono davvero l'uno dall'altro,
  e la base va scritta nel recap.
- **Nessun merge** finché la meccanica non è `PASS` al livello richiesto.
- Ordine di merge: dalla base verso l'alto (M1 → M2 → M3 → …), uno alla volta,
  eseguendo la suite dopo ciascuno.
- Branch scartati: stato `SCARTATA`, elencati nel recap, mai uniti.
- Nessun push senza richiesta esplicita.

## 8. Template

### 8.1 Scheda diagnosi
```
MECCANICA: <nome>    ID: <Mn>
Stato attuale: <vedi sezione 1>
Classe: <A | B | C | D>
Codice esistente rilevante: <file/funzioni>
Vincoli letti: <documenti repo>
Dipendenze: <servizi, chiavi, driver, permessi, altre meccaniche>
Decisioni utente necessarie: <sì/no, quali>
Rischi: <sicurezza, audio, collisioni>
Lacune (Da verificare): <...>
Livelli di convalida raggiungibili ora: <L1 L2 L3 L4>
Conclusione: <1-2 righe>
```

### 8.2 File implementativo (`docs/impl/<ID>-<nome>.md`)
```
# <ID> – <nome>
## Obiettivo
## Fuori perimetro
## Interfaccia (strumento, parametri, errori, frasi vocali suggerite)
## Modifiche per file (file | funzione | modifica)
## Test automatici (L1)
## Prove: L2 | L3 | L4 (comando, esito atteso)
## Criteri di accettazione (osservabili, con livello minimo)
## Rollback
## Verdetto di fattibilità (fase 3)
```

### 8.3 Verdetto di fattibilità
```
Checklist 1..10: <SÌ/NO/DA VERIFICARE>
Esito: <PROCEDI | RIVEDI PIANO | VERIFICA | NON FATTIBILE>
Motivazione: <...>
```

### 8.4 Recap per meccanica
```
MECCANICA: <ID nome>     Branch: <nome>  Base: <branch>  Commit: <hash...>
Fatto: <...>
L1: <comando, N passati/totali>
L2: <esito>   L3: <esito/bloccato>   L4: <esito/bloccato>
Stato assegnato: <sezione 1>
Blocchi: <cosa, chi deve agire, come sbloccare>
Limiti residui: <...>
Docs aggiornati: <sì/no>
Prossima in coda: <...>
```

### 8.5 Recap finale
```
Chiuse (PASS): <n>   Non convalidate: <n>   In attesa di scelta: <n>   Scartate: <n>
Blocchi aperti e responsabile: <...>
Branch pronti al merge e ordine: <...>
Prove non eseguite: <...>
Prossimi passi: <...>
```

## 9. Coda iniziale (dallo stato dei cicli M0-M4)

Lo stato sotto è quello **riportato nei log dell'agente**: va ricontrollato
in fase 0 sul checkout reale prima di fidarsene.

| ID | Meccanica | Stato riportato | Cosa manca |
|---|---|---|---|
| B0 | Connessione Gemini Live | Bloccata ("Connecting…" riportato) | Diagnosi col percorso reale (sezione 5.2), eseguita dall'utente |
| M0 | Discovery | PASS | — |
| M1 | Browser integrato (siti, YouTube, giochi web dentro Jarvis) | IMPLEMENTATA – NON CONVALIDATA | L3/L4; verificare sovrapposizione col controllo browser esistente in `actions/` |
| M2 | Click e tasti (link, pulsanti, giochi tipo Snake) | IMPLEMENTATA – NON CONVALIDATA | Dipende da M1; rischio: pagine che rifiutano eventi sintetici, verificare fallback |
| M3 | Screen reader personale ("leggi la pagina") | IMPLEMENTATA – NON CONVALIDATA | Dipende da M1 e audio; verificare riuso di `core/accessibility.py` (OCR, NVDA, `pyttsx3`, hotkey) per non duplicare |
| M4 | NVIDIA – monitoraggio GPU (`nvidia-smi`) | Implementata, 125 test riportati, interrogazione GPU reale riportata | Conferma della scelta (era stata proposta C); L3/L4 |
| M4-alt | Moonlight/Sunshine | SCARTATA (scelta provvisoria dell'agente) | Non unire; riaprire solo su richiesta |
| M5 | Merge ordinato dei branch | DA FARE | Solo dopo PASS di M1-M4, uno per volta con suite |

Ordine di lavoro:
1. **Fase 0** sul checkout reale (identità, tree, segreti, baseline).
2. **B0** in parallelo come attività dell'utente.
3. **L2/L1 di M1-M4** dove possibile senza Gemini; registrare gli screenshot.
4. **L3/L4** appena Gemini è connesso, nell'ordine M1 → M2 → M3 → M4.
5. **M5** merge.

## 10. Prompt di sessione (da incollare all'agente)

> Segui `PROCEDURA_IMPLEMENTATIVA_JARVIS.md`. Esegui la Fase 0 sul checkout
> reale e riportami: remote, branch, stato Git, baseline test, stato Gemini.
> Poi prendi la prima voce della coda non bloccata ed esegui le fasi 1→8 senza
> saltarne nessuna, dichiarando il livello di prova (L1-L4) di ogni esito.
> Non unire branch, non fare push, non toccare il codice Gemini Live senza un
> errore osservato, non eseguire script che trasmettono credenziali. Fermati
> e chiedimi se serve una mia decisione, se un gate fallisce due volte di fila
> o se serve una prova che posso fare solo io (microfono, vista, Gemini).
