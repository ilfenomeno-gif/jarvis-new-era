# Procedura implementativa GEV-Jarvis (ciclo per ogni meccanica)

Questo file definisce la procedura **obbligatoria e identica** da eseguire per
ogni meccanica e per ogni step dell'integrazione GEV → Jarvis, in loop, fino
all'esaurimento della coda. Si basa sullo stato riportato in
`docs/MECCANICHE_GEV_JARVIS.md` nella repository Jarvis (Funzionante / Semi
funzionante / Non funzionante in Jarvis).

## 0. Regole fisse

1. **Una meccanica alla volta.** Non si apre la successiva finché la corrente
   non ha chiuso la fase 8 (recap).
2. **Nessuna fase saltata, nessuna fase riordinata.** Ogni fase produce un
   artefatto scritto (nota, file, log). Senza artefatto la fase non è chiusa.
3. **Nessuno stato senza prova.** “Funzionante” si scrive solo con evidenza
   riproducibile (test automatico o prova manuale descritta). Test Python che
   verificano l'inoltro non provano il movimento visivo del globo; prove
   testuali non provano il microfono. Dichiarare sempre il livello di prova.
4. **Non confondere GEV con Jarvis.** “Non funzionante in Jarvis” = manca
   l'azione/bridge, non che il codice GEV sia guasto.
5. **Niente invenzioni.** Se un dato non è verificato (es. Janet 27,
   `ask_about`), resta `Da verificare` finché non c'è riscontro nel codice.
6. **Granularità separata:** il ciclo di verifica/convalida è uno per
   meccanica; il commit è uno per blocco implementativo coerente. Se più
   meccaniche condividono lo stesso ramo/dispatcher/test parametrizzato,
   possono appartenere allo stesso commit implementativo senza essere fuse
   nei rispettivi cicli di convalida.
7. **Git:** lavoro solo sul branch `feat/gev-integration`; nessun push né
   merge su `main`; non includere modifiche preesistenti senza averle prima
   classificate e verificate.
8. **Se una fase fallisce** si torna alla fase indicata nel gate (sezione 4),
   non si prosegue.
9. **Chiavi e provider:** i feed dipendenti da chiavi/quote non si dichiarano
   falliti o riusciti in modo assoluto; si registra l'esito della prova e le
   condizioni (rete, chiave, copertura).
10. **Licenze dati e rilascio:** la licenza MIT del codice GEV non implica che
    ogni dataset incluso abbia la stessa licenza. Prima di push o pubblicazione,
    inventariare i dataset redistribuiti e verificare/decidere separatamente se
    mantenerli nel repository con la licenza applicabile, recuperarli a runtime
    o distribuirli con termini separati. La semplice presenza di un file
    LICENSE/provenienza non equivale a una verifica di compatibilità o a un
    parere legale. Se la decisione non è documentata, il gate di rilascio resta
    bloccato e si scrive `> Da verificare`.

## 1. Fase 0 — Preflight

Da completare prima di iniziare una meccanica o una sequenza di cicli.

**Controlli**

1. Verificare branch e working tree in entrambe le repo. Devono essere pulite,
   oppure ogni modifica preesistente deve essere inventariata per file/ambito,
   esaminata e tenuta fuori dagli interventi/commit correnti finché non è
   esplicitamente classificata.
2. Verificare che Jarvis sia avviabile e che GEV sia disponibile su
   `127.0.0.1:4173` quando il ciclo richiede prove live. Non avviare né
   terminare processi dell'utente senza poter osservare/controllare in modo
   affidabile la prova richiesta; annotare come bloccato se manca una UI
   controllabile.
3. Registrare lo stato iniziale dei test pertinenti (baseline), inclusi
   comando, conteggi ed errori preesistenti. La baseline non equivale alla
   verifica post-implementazione della fase 5.
4. Per modifiche locali non pertinenti (ad esempio mappe storiche GEV),
   leggere diff, test e file aggiunti; classificarle come incluse,
   indipendenti da conservare, oppure bloccanti/non sicure. Non committare
   materiale non esaminato o non attribuibile.
5. Se il blocco distribuisce dataset o altri contenuti di terzi, annotare la
   provenienza e i termini dichiarati; segnalare le decisioni di distribuzione
   ancora aperte senza dedurne la compatibilità dal solo codice.

**Output:** scheda preflight con branch/HEAD, stato Git per repo, baseline
test e disponibilità dell'ambiente live.

**Gate:** il perimetro delle modifiche è chiaro e non si rischia di sovrascrivere
o includere lavoro altrui/non classificato. I prerequisiti live non disponibili
bloccano la fase 6, non la sola lettura o pianificazione; non si dichiara
superata la convalida in loro assenza.

## 2. Ciclo (vista d'insieme)

```
[Preflight 0] → [Coda] → 1 Analisi/Diagnosi → 2 Piano (file implementativo)
       → 3 Diagnosi di fattibilità del piano → 4 Implementazione
       → 5 Verifica tecnica → 6 Convalida (prova reale)
       → 7 Aggiornamento inventario → 8 Recap → prossima meccanica
```

Ogni fase ha: **input**, **azioni**, **output**, **gate** (condizione per
passare oltre).

## 3. Fasi

### Fase 1 — Analisi e diagnosi della meccanica

**Input:** voce dell'inventario, repo Jarvis e repo GEV.

**Azioni**
- Leggere la riga dell'inventario: stato attuale, comando suggerito, limiti.
- Individuare nel codice GEV la capacità (schema in
  `src/voice/actionSchemas.js`, dispatcher in `src/voice/gevActions.js`,
  UI/template, eventuale tool MCP in `src/tools/surfaces.js`).
- Individuare nel codice Jarvis cosa esiste già (`plugins/gev_plugin.py`,
  `ui.py` / `_GEV_LAYERS`, client MCP, messaggi bridge `gev:*`).
- Classificare la meccanica:
  - **A. Da validare** (codice presente, prova parziale);
  - **B. Da esporre** (esiste in GEV, manca azione/bridge Jarvis);
  - **C. Da progettare** (manca anche il supporto lato GEV o è ambigua);
  - **D. Non fattibile / fuori ambito** (es. richiede feature solo dev-server).
- Annotare dipendenze: chiavi API, provider, protocollo embed (`gev:view` è
  vista assoluta), collisioni con tool MCP esistenti (es. `fly_to` vs
  `show_in_gods_eye_view`).

**Output:** *Scheda diagnosi* (template 4.1).

**Gate:** classe assegnata, dipendenze elencate, lacune di conoscenza
marcate `Da verificare`. Se classe D → salto alla fase 8 con motivazione.

### Fase 2 — Elaborazione del file implementativo

**Input:** scheda diagnosi.

**Azioni:** scrivere il file `impl/<NN>-<nome-meccanica>.md` con il template
4.2: obiettivo, perimetro (cosa NON si fa), modifiche per file, interfaccia
(nome azione, parametri, range, errori), frase naturale suggerita per Gemini,
test da scrivere, prova manuale, criteri di accettazione, rollback.

**Output:** file implementativo.

**Gate:** ogni modifica indica file e funzione; ogni criterio di accettazione
è osservabile (passa/non passa).

### Fase 3 — Analisi e diagnosi del file implementativo (fattibilità)

**Domanda guida:** “Posso davvero farlo così, ora, senza rompere altro?”

**Checklist (tutte con esito SÌ / NO / DA VERIFICARE)**
1. I file e le funzioni citati esistono davvero (verificati aprendo il codice)?
2. L'interfaccia è compatibile col protocollo bridge/embed attuale?
3. Evita collisioni di nome con azioni plugin o tool MCP esistenti?
4. Le dipendenze (chiavi, provider, rete) sono disponibili in locale?
5. Esiste un modo di provarlo (test automatico + prova manuale definita)?
6. Il rollback è realizzabile con un singolo revert di commit?
7. Impatto sulle altre azioni (`reset`, layer, follow, annotazioni) valutato?
8. Granularità del commit: le modifiche sono isolate per blocco
   implementativo coerente? Se il codice è condiviso fra più meccaniche,
   pianificare un commit per il blocco condiviso e mantenere cicli/prove/stati
   distinti per ciascuna meccanica. Spezzare in sotto-step solo se separabili
   senza duplicare o riscrivere artificialmente il codice.

**Esito:**
- **Tutto SÌ** → fase 4.
- **Qualche NO** → tornare alla fase 2 e correggere il piano.
- **DA VERIFICARE** → eseguire la verifica (lettura codice, prova rapida) e
  ripetere la fase 3.
- **Impossibile** → classe D, fase 8 con motivazione.

**Output:** *Verdetto di fattibilità* (template 4.3), allegato al file
implementativo.

### Fase 4 — Implementazione

**Azioni**
- Creare/aggiornare solo i file elencati nel piano.
- Scrivere prima i test (o contemporaneamente), poi il codice.
- Mantenere naming coerente con le azioni esistenti (`camera_*`, `historical_*`).
- Rifiutare input fuori range con errore esplicito (come per alias layer non
  supportati).
- Commit per blocco implementativo coerente:
  `feat(gev): <blocco> – <sintesi>`. Un commit comune può supportare più
  meccaniche correlate; citarne l'hash in ogni scheda di ciclo interessata.
- Prima di committare: verificare `git diff --cached`, includere soltanto i
  file/hunks classificati nel preflight e non sovrascrivere modifiche locali.

**Output:** diff + commit.

**Gate:** il codice compila/si avvia; nessun file fuori piano modificato
(`git diff --stat` coerente col piano).

### Fase 5 — Verifica tecnica (automatica)

**Azioni**
- Eseguire i test mirati della meccanica.
- Eseguire l'intera suite esistente (almeno `pytest tests/test_gev_mcp_client.py -q`
  e i test del plugin) per escludere regressioni.
- Registrare numero di test passati/falliti.

**Gate:** 0 fallimenti. In caso contrario: correggere in fase 4 (se bug) o
2 (se piano sbagliato). **Mai** modificare un test solo per farlo passare
senza motivarlo per iscritto.

### Fase 6 — Convalida (prova reale)

**Azioni**
- Eseguire la prova manuale definita nel piano, nell'ordine:
  1. prova **testuale** (UI testuale Jarvis);
  2. prova **visiva** nella finestra GEV integrata (il globo si muove /
     il layer compare / l'etichetta appare);
  3. prova **vocale** col microfono (solo se in perimetro).
- Registrare per ogni prova: comando esatto usato, risposta/log (es.
  `gev:ready`, chiamata MCP nel log), esito visivo, data, condizioni
  (rete, chiavi, provider).
- Provare almeno un caso d'errore (parametro fuori range, target non trovato,
  feed non disponibile).

**Gate → stato da assegnare**
| Evidenza raccolta | Stato |
|---|---|
| Test automatico + prova visiva riuscita | **Funzionante** (specificare livello: testuale / visivo / vocale) |
| Solo test automatico o solo log di dispatch | **Semi funzionante** |
| Nessuna azione Jarvis | **Non funzionante in Jarvis** |
| Dato non provabile | **Da verificare** |

Se la prova visiva fallisce con test verdi: tornare alla fase 1 (diagnosi),
perché il difetto è nel bridge/protocollo, non nel solo inoltro Python.

### Fase 7 — Aggiornamento inventario e documentazione

**Azioni**
- Aggiornare la riga della meccanica in Jarvis
  `docs/MECCANICHE_GEV_JARVIS.md`
  (stato, comando, evidenza) usando la legenda esistente.
- Se cambia l'elenco di azioni plugin o alias layer, aggiornare le tabelle
  “Comandi Jarvis supportati” e “Layer effettivamente mappati”.
- Aggiornare `docs/GEV_INTEGRATION.md` se cambia il protocollo.
- Aggiungere la voce a `09-prompt-history` / cartella documentazione del
  progetto.

**Gate:** inventario e codice dicono la stessa cosa.

### Fase 8 — Recap e passaggio al ciclo successivo

**Azioni:** compilare il *Recap* (template 4.4) e riportarlo in chat prima
di iniziare la meccanica seguente. Poi:
1. riprendere la coda (sezione 5);
2. scegliere la prossima voce per priorità;
3. ripartire dalla Fase 1.

**Condizione di fine ciclo:** coda vuota **oppure** tutte le voci rimaste sono
classe D / “Da verificare” bloccate da dipendenze esterne. A quel punto
produrre il *Recap finale* (template 4.5).

## 3. Tabella di rientro (cosa fare se un gate fallisce)

| Fase che fallisce | Si torna a | Motivo tipico |
|---|---|---|
| 0 (preflight) | 0 | Working tree non classificata, baseline assente o ambiente non pronto |
| 3 (fattibilità) | 2 | Piano incompleto o incompatibile |
| 4 (implementazione) | 2 o 3 | Scoperto vincolo non previsto |
| 5 (test) | 4 | Bug nel codice |
| 5 (test) | 2 | Piano/criteri errati |
| 6 (prova reale) | 1 | Il test non rappresentava il comportamento reale |
| 7 (inventario) | 6 | Evidenza insufficiente per lo stato dichiarato |

Dopo **2 rientri consecutivi** sulla stessa fase: fermarsi, riportare il
blocco all'utente con ipotesi e opzioni, senza insistere.
Non contare come fallimento di fattibilità una semplice scelta di granularità:
prima verificare se la feature è un blocco condiviso che richiede un commit
comune.

## 4. Template

### 4.1 Scheda diagnosi

```
MECCANICA: <nome>              ID: <NN>
Stato attuale inventario: <Funzionante | Semi | Non funzionante in Jarvis>
Classe: <A validare | B esporre | C progettare | D non fattibile>
Lato GEV: <file:riga, schema, dispatcher, UI>
Lato Jarvis: <plugin/ui/bridge esistente>
Dipendenze: <chiavi, provider, rete, dev-server>
Rischi/collisioni: <...>
Lacune (Da verificare): <...>
Conclusione: <1-2 righe>
```

### 4.2 File implementativo (`impl/<NN>-<nome>.md`)

```
# <NN> – <nome meccanica>
## Obiettivo
## Fuori perimetro
## Interfaccia
- Azione/tool: <nome>   Parametri: <nome, tipo, range>   Errori: <...>
- Frase suggerita (Gemini): “Jarvis, ...”
## Modifiche per file
| File | Funzione/sezione | Modifica |
## Test automatici da scrivere
## Prova manuale (testuale / visiva / vocale)
## Criteri di accettazione (osservabili)
## Rollback
## Verdetto di fattibilità  (compilato in fase 3)
```

### 4.3 Verdetto di fattibilità

```
Checklist 1..8: <SÌ/NO/DA VERIFICARE ciascuno>
Esito: <PROCEDI | RIVEDI PIANO | VERIFICA | NON FATTIBILE>
Motivazione: <...>
```

### 4.4 Recap per meccanica

```
MECCANICA: <nome>   Commit: <hash>
Cosa è stato fatto: <...>
Test: <N passati / N totali>
Prove reali: testuale <esito> | visiva <esito> | vocale <esito/non eseguita>
Stato finale assegnato: <...>
Limiti residui: <...>
Inventario aggiornato: <sì/no>
Prossima meccanica in coda: <nome>
```

### 4.5 Recap finale

```
Meccaniche chiuse: <n>  (Funzionante: x | Semi: y | Non in Jarvis: z | Non fattibili: w)
Ancora aperte e perché: <...>
Prove non eseguite (es. microfono): <...>
Commit sul branch feat/gev-integration: <elenco>
Prossimi passi consigliati: <...>
```

## 5. Coda iniziale (derivata dall'inventario)

Priorità: prima **validare** ciò che è già codificato (classe A), poi
**esporre** ciò che GEV ha già (classe B), poi **progettare** (classe C).

### Priorità 1 — Da validare (Semi funzionante)

| ID | Meccanica | Prova mancante |
|---|---|---|
| 05 | Fly-to (`show_in_gods_eye_view`) | Verifica visiva della camera risultante |
| 06 | CCTV (toggle) | Frame/feed e geometria |
| 07 | Tool MCP di ricerca (`gev_mcp_*`) | Query su voli/terremoti con esito registrato |
| 08 | Directions / routing | Percorso visibile end-to-end |

### Cicli camera chiusi tecnicamente; revisione utente richiesta

| ID | Meccanica | Evidenza conservata | Stato |
|---|---|---|---|
| 01 | Zoom incrementale (`camera_zoom`) | `impl/01-zoom-visivo.png` | Testuale e screenshot registrati; revisione personale richiesta ancora aperta |
| 02 | Inclinazione camera (`camera_tilt`) | `impl/02-tilt-visivo.png` | Testuale e screenshot registrati; revisione personale richiesta ancora aperta |
| 03 | Rotazione camera (`camera_rotate`) | `impl/03-rotate-visivo.png` | Testuale e screenshot registrati; revisione personale richiesta ancora aperta |
| 04 | Reset camera (`camera_reset`) | `impl/04-camera-reset-visivo.png` | Testuale e screenshot registrati; revisione personale richiesta ancora aperta |

### Priorità 2 — Da esporre (esiste in GEV, manca in Jarvis)

| ID | Meccanica | Nota |
|---|---|---|
| 09 | Estensione `_GEV_LAYERS` (military, traffic, radio, transit, bikeshare, ALPR, cyclones…) | Un alias per ciclo; verificare che l'ID layer GEV esista |
| 10 | Map Stack (`set_map_stack`) | Dipende da chiavi (Google 3D, Cesium ion) |
| 11 | Visual styles | Preset da schema voice GEV |
| 12 | Detection overlay (`set_detection`, `densityPct`) | Parametri multipli: valutare sotto-step |
| 13 | `move_camera` (orbit/pan/tilt/rotate/stop) | Richiede nuovo messaggio bridge, non `gev:view` assoluto |
| 14 | Cockpit view / Contacts mode / Global Context | Verificare dipendenza dal tracking attivo |
| 15 | Timeline meteo e layer meteo | Controlli seek/play non esposti |
| 16 | Scene Director (shot, playback, import/export) | Spezzare in sotto-step |
| 17 | Share Links | Funzione distinta dal Director |
| 18 | Radio | `find_radio_stations` escluso dalla superficie MCP: valutare |

### Priorità 3 — Da progettare / chiarire

| ID | Meccanica | Nota |
|---|---|---|
| 19 | Pan/orbit continui | Serve nuovo messaggio bridge |
| 20 | Janet 27 | `Da verificare`: nessun riscontro nel codice |
| 21 | `ask_about` / world knowledge | `Da verificare`: nome azione non trovato nello schema |
| 22 | AI HUD Summary, Celestial, TR-3B | Controlli HUD/UI: valutare utilità per Jarvis |
| 23 | POWER UP (gestione chiavi) | Limitato al dev server: probabile classe D |
| 24 | Prova vocale reale (microfono) | Trasversale: da eseguire a fine ciclo su tutte le azioni Funzionanti |
| 25 | Instradamento reset camera | Decidere/validare la frase: “torna alla vista globale” ha selezionato `reset` completo, mentre la frase che nomina il plugin e la sola camera seleziona `reset_camera` |
| 26 | Comando GEV prima di `ready` | Verificare e rendere coerente la risposta quando GEV non è pronto; è stato osservato un fallimento esplicito su chiamata forzata al plugin e un instradamento errato verso `[Settings] zoom_in` con frase generica |

Regola di aggiornamento coda: quando una meccanica si chiude, cancellarla
dalla coda e annotare nel recap l'ID e lo stato finale. Se emergono
sotto-step, aggiungerli con ID nuovo e mantenerli come cicli di verifica
distinti. Meccaniche che condividono un blocco implementativo possono puntare
allo stesso commit; non duplicare né riscrivere il codice solo per forzare un
commit per ciascun ID.

## 6. Definizione di “fatto” per una meccanica

Una meccanica è chiusa solo se **tutte** vere:
- file implementativo presente e con verdetto di fattibilità;
- codice nel commit del blocco implementativo corrispondente, nessuna
  regressione nella suite (il medesimo hash può essere condiviso da più
  meccaniche);
- prova reale registrata con comando, esito e condizioni;
- stato nell'inventario coerente con l'evidenza e con il livello di prova;
- recap compilato e riportato in chat.

## 7. Istruzione operativa sintetica (da incollare all'inizio di ogni sessione)

> Segui `PROCEDURA_IMPLEMENTATIVA_GEV_JARVIS.md`. Esegui prima la Fase 0.
> Poi prendi la prima voce della coda. Esegui le fasi 1→8 senza saltarne
> nessuna: analisi e diagnosi,
> file implementativo, diagnosi di fattibilità, implementazione, verifica
> tecnica, convalida reale, aggiornamento inventario, recap. Mostrami il
> recap, poi passa alla voce successiva. Fermati e avvisami se un gate
> fallisce due volte di fila o se serve una prova che puoi fare solo tu
> (visiva o vocale).
