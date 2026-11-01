# 01 — Zoom incrementale (`camera_zoom`)

Data della ricognizione: 2026-10-04.

## Fase 1 — Analisi e diagnosi

**Stato nell'inventario:** Funzionante (prova testuale e visiva nella finestra
integrata; prova microfono non eseguita, non richiesta per chiudere questo
ciclo).

**Classe:** A — da validare.

**Lato Jarvis verificato nel checkout locale**

- `plugins/gev_plugin.py:718-738` accetta `zoom` con `level` `in`/`out` e
  produce `camera_zoom`; è presente anche l'opzione esplicita `altitude_m`
  con controllo del range.
- `ui.py:2823-2849` tratta le azioni `camera_*`, prepara una camera completa
  con valori predefiniti e, per `camera_zoom`, dimezza/raddoppia l'altitudine
  entro i limiti oppure usa `altitude_m`.
- `ui.py:4578-4582` include `camera_zoom` nella allowlist di
  `send_to_gev()`.
- `tests/test_gev_mcp_client.py:367-407` verifica le risposte per zoom in/out
  e l'inoltro del payload. Questo prova il dispatch Python, non il movimento
  del globo.

**Lato GEV verificato:** la voce nativa dichiara `adjust_camera_zoom` con
`direction` `in`/`out` e `amount` `little`/`medium`/`lot`
(`src/voice/actionSchemas.js:94-108`; dispatcher
`src/voice/gevActions.js:961-962`). È un tool della voce nativa GEV, distinto
dall'azione Jarvis `zoom` e dal messaggio embed `camera_zoom`; la selezione
Jarvis end-to-end è stata verificata nella Fase 6, dopo `GEV: ready`.

**Protocollo e dipendenze:** il bridge usa l'azione `camera_zoom`, non
`gev:view` come nome d'azione; il dispatcher UI costruisce/invia una vista.
Lo zoom non richiede una chiave provider. Riferimenti implementativi:
`plugins/gev_plugin.py:883-907`, `ui.py:2823-2899`,
`ui.py:2944-2955`.

**Rischi e lacune:** al primo avvio la finestra Jarvis e il listener GEV non
erano attivi; dopo aver avviato Jarvis, il listener `127.0.0.1:4173` è
diventato disponibile e la UI integrata ha restituito `GEV: ready`. Un comando
zoom prima di `ready` è fallito esplicitamente; non va contato come prova
negativa della camera. Dopo `ready`, `zoomma dentro` e `zoomma fuori` hanno
prodotto rispettivamente `camera_zoom` con `level=in` e `level=out`. Le
schermate della vista integrata mostrano la scena cambiare con gli zoom; più
zoom-in consecutivi avvicinano la vista fino a perdere dettaglio utile, mentre
`camera_reset` ripristina la vista globale. Non è stato letto un valore
numerico dell'altitudine dalla pagina.

Le modifiche GEV alle mappe storiche sono state committate separatamente
(`2bc902b`, `feat(gev): add historical map scenarios`), includendo la
provenienza/licenza del dataset fallback. Il dispatcher Jarvis condiviso da
zoom, tilt, rotate e reset è stato committato come blocco
(`46ded87`, `feat(gev): add historical and camera dispatch`); l'inventario
non tracciato non è incluso nel commit Jarvis.

**Gate separato prima della pubblicazione:** `package.json` dichiara MIT per
il progetto GEV; `DATA_SOURCES.md` dichiara GPLv3 per l'indice storico
redistribuito. Aver incluso provenienza e testo licenza non decide la
compatibilità o la strategia di distribuzione. Prima di push/pubblicazione:
`> Da verificare` — decidere e documentare se mantenere il dataset, scaricarlo
a runtime o applicare termini separati. Nessuna conclusione legale viene
formulata in questa scheda.

**Conclusione:** il test automatico e la prova testuale/visiva confermano lo
zoom incrementale nel percorso UI integrato. La frase deve essere inviata solo
dopo `GEV: ready`: prima dell'apertura GEV è stata instradata verso
`[Settings] zoom_in`, non verso il bridge GEV.

## Fase 2 — Piano implementativo

### Obiettivo

Convalidare l'azione incrementale zoom già presente: `level="in"` dimezza
l'altitudine corrente (minimo 50 m), `level="out"` la raddoppia (massimo
20.000.000 m), e l'altitudine esplicita è inoltrata con validazione.

### Fuori perimetro

- Non modificare `tilt`, `rotate`, `reset_camera` o il fly-to MCP.
- Non aggiungere controlli nuovi a GEV e non cambiare altri stati/layer.
- Non modificare né includere nei commit le modifiche GEV locali ai mappe
  storiche/dati.

### Interfaccia e criteri osservabili

| Elemento | Valore |
|---|---|
| Azione plugin | `zoom` |
| Payload incrementale | `{"action":"camera_zoom","params":{"level":"in"|"out"}}` |
| Payload assoluto | `{"action":"camera_zoom","params":{"altitude_m":N}}` |
| Frase suggerita | “Jarvis, zoomma dentro” / “Jarvis, zoomma fuori” |
| Accettazione tecnica | Test schema/dispatch passano; input altitudine fuori range è rifiutato |
| Accettazione visiva | Nella finestra integrata la camera cambia scala nella direzione richiesta |
| Rollback | Revert del commit condiviso del bridge camera; coinvolge zoom, tilt, rotate e reset |

### File previsti se occorre correggere il comportamento

| File | Funzione/sezione | Intervento |
|---|---|---|
| `plugins/gev_plugin.py` | ramo `action == "zoom"` e mappatura `camera_actions` | Correggere solo l'inoltro/validazione zoom se la prova individua un difetto |
| `ui.py` | ramo `camera_zoom` in `_on_gev_send()` | Correggere solo il calcolo/applicazione dell'altitudine se la prova individua un difetto |
| `tests/test_gev_mcp_client.py` | test parametrizzati camera | Aggiungere o correggere il test che riproduce il difetto |
| `docs/GEV_INTEGRATION.md` | protocollo camera | Aggiornare solo se cambia il protocollo |
| `docs/MECCANICHE_GEV_JARVIS.md` | riga Zoom incrementale | Aggiornare dopo evidenza reale, non sulla sola base dei test di inoltro |

## Fase 3 — Verdetto di fattibilità

| # | Controllo | Esito | Evidenza / nota |
|---|---|---|---|
| 1 | File e funzioni esistono | SÌ | Riferimenti nel codice Jarvis elencati sopra |
| 2 | Protocollo compatibile | SÌ | UI allowlist e ramo `camera_zoom` corrispondono al payload plugin |
| 3 | Nessuna collisione di dispatch | SÌ dopo `GEV: ready`, con precondizione | Prima di aprire GEV, il comando generico ha selezionato `[Settings] zoom_in`; dopo `GEV: ready`, ha selezionato `camera_zoom` |
| 4 | Dipendenze locali disponibili | SÌ | Jarvis ha avviato GEV; listener verificato su `127.0.0.1:4173`; non serve una chiave provider per il calcolo camera |
| 5 | Verifica riproducibile definita | SÌ, completata per questo ciclo | 25 test mirati passati; input testuale, dispatch e modifica visiva provati nella finestra integrata |
| 6 | Rollback singolo realizzabile | SÌ | `46ded87` contiene il blocco condiviso camera e dispatcher; il revert resta unitario per il blocco |
| 7 | Impatto sulle altre azioni valutato | SÌ nel codice e nel runtime | La vista mantiene gli altri campi camera; tilt, rotate e reset sono stati verificati in prove separate |
| 8 | Dimensione di un commit per meccanica | SÌ, per blocco implementativo | Un commit condiviso copre i quattro controlli camera; i cicli e le evidenze restano distinti |

**Esito primo tentativo: RIVEDI PIANO.** Rientro dalla fase 3 alla fase 2
(1° rientro): il piano non specificava un metodo verificato per isolare il
commit.

### Fase 2 — Revisione del piano (procedura corretta)

Piano rivisto: implementare e committare il blocco condiviso
`camera_zoom`/`camera_tilt`/`camera_rotate`/`camera_reset` come una sola unità
autosufficiente; poi mantenere le voci 01, 02, 03 e 04 come quattro cicli
distinti di prova visiva e aggiornamento dell'inventario. Non selezionare
hunks per singola azione né duplicare il dispatcher.

### Fase 3 — Seconda analisi di fattibilità

La verifica del diff con `git diff --unified=0` mostra che il piano a blocco
condiviso è coerente con il codice. Checklist rivista:

La checklist seguente fotografa la fattibilità prima della prova live e dei
commit; gli esiti aggiornati sono riportati nelle Fasi 4 e 6–8.

| # | Controllo | Esito | Evidenza / nota |
|---|---|---|---|
| 1 | File e funzioni esistono | SÌ | Plugin, `MainWindow._on_gev_send`, `JarvisUI.send_to_gev` e test sono nel diff locale |
| 2 | Protocollo compatibile | SÌ nel codice | `camera_*` è gestito dal bridge e tradotto in `gev:view` |
| 3 | Nessuna collisione di dispatch | SÌ nel codice | Le azioni camera usano nomi `camera_*`; fly-to resta al MCP nativo |
| 4 | Dipendenze locali disponibili | SÌ per le prove automatiche | Nessuna chiave richiesta; per UI live serve avviare Jarvis/GEV |
| 5 | Verifica riproducibile | SÌ | Test Python parametrizzati disponibili; visiva ancora da eseguire |
| 6 | Rollback singolo | SÌ | Un commit del blocco comune può essere revertito come unità |
| 7 | Impatto sugli altri controlli | SÌ nel codice | La camera completa mantiene lat/lon/heading/pitch e valida i range; test live pendente |
| 8 | Granularità commit | SÌ | Le quattro azioni condividono mappatura plugin, ramo UI e test parametrizzato; un commit per blocco |

**Esito aggiornato: PROCEDI dopo il gate del preflight sui materiali esterni.**
La procedura è stata corretta; i due rientri precedenti erano causati dalla
regola di granularità non adeguata e non sono più un blocco. Non si committa
ancora il blocco finché non è chiaro se il dispatcher più ampio e la feature
storica GEV possano essere inclusi senza incorporare materiale non classificato.
Il gate è stato poi risolto con commit distinti per il bridge Jarvis e la feature
storica GEV, come registrato nella Fase 4.

## Fase 4 — Implementazione

Non sono state necessarie modifiche aggiuntive durante la convalida del ciclo.
Il blocco Jarvis condiviso risulta committato:

- `46ded87 feat(gev): add historical and camera dispatch`
  (`docs/GEV_INTEGRATION.md`, `plugins/gev_plugin.py`,
  `tests/test_gev_mcp_client.py`, `ui.py`).
- `2bc902b feat(gev): add historical map scenarios` nel repository GEV
  (controller e test storici, documentazione, dati e licenza del fallback).

L'inventario `docs/MECCANICHE_GEV_JARVIS.md` rimane fuori dal commit Jarvis.

## Fase 0 — Preflight registrato

- Branch Jarvis e GEV: `feat/gev-integration`.
- Al primo controllo il Jarvis GUI non era attivo e GEV non ascoltava su
  `127.0.0.1:4173`; il preflight live è stato ripetuto dopo l'avvio.
- Dopo il commit Jarvis, il solo file non tracciato rimasto è
  `docs/MECCANICHE_GEV_JARVIS.md`, non incluso in `46ded87`.
- GEV è pulito dopo il commit `2bc902b`; Jarvis è ahead di un commit rispetto
  a `origin/feat/gev-integration`, senza push.
- Runtime Node GEV locale `.node/node.exe`: `v24.14.0`, corrisponde alla
  versione minima dichiarata dal `package.json`.
- Test di baseline/preflight: `pytest tests/test_gev_mcp_client.py -q` →
  25 passed; `node --test src/app/historicalMap.test.mjs` dalla root GEV →
  12 passed. Sono baseline osservate sulla working tree dirty, non su HEAD
  pulito.
- Classificazione: dispatcher e bridge Jarvis sono un blocco condiviso per
  quattro cicli camera; modifiche GEV sono una feature storica separata. Il
  commit GEV ha registrato la fonte upstream e incluso la licenza GPLv3
  associata all'indice fallback.

```text
Jarvis: 25 passed / 25
GEV historical maps: 12 passed / 12
```

La prova Python verifica gli asserimenti su schema e inoltro, non il movimento
del globo. La suite GEV copre il controller storico, non la validità
storiografica dei dati.

## Fase 6 — Convalida reale

Data: 2026-10-04. Jarvis è stato avviato dal collegamento desktop; GEV ha
iniziato ad ascoltare su `127.0.0.1:4173`. La UI testuale ha confermato
`GEV: ready` dopo il comando di apertura.

| Prova | Comando / evidenza | Esito |
|---|---|---|
| Testuale zoom-in | “Jarvis, zoomma dentro” → `camera_zoom`, `level=in`; risposta “Zoom avanti, Signore.” | Pass |
| Testuale zoom-out | “Jarvis, zoomma fuori” → `camera_zoom`, `level=out`; risposta “Zoom indietro, Signore.” | Pass |
| Visiva | Nella finestra integrata la scena cambia scala: zoom-in ripetuto porta la vista a un dettaglio ravvicinato; zoom-out restituisce una vista più ampia. `camera_reset` riporta poi la vista globale. | Pass qualitativo; la UI non esponeva una misura numerica dell'altitudine |
| Vocale | Non eseguita con microfono | Fuori dal gate di questo ciclo; prova trasversale da pianificare |

Una prova zoom-in inviata prima che la pagina integrata restituisse `GEV: ready`
è fallita con “GEV interface is not ready”; dopo `ready`, lo stesso comando è
stato dispatchato correttamente. I test automatici verificano schema/inoltro,
non l'esito visuale.

Screenshot della finestra con log e scena: [01-zoom-visivo.png](./01-zoom-visivo.png).
La revisione personale dello screenshot richiesta dal proprietario del progetto
non è ancora attestata.

## Fase 7 — Aggiornamento inventario

La riga Zoom incrementale è stata aggiornata a **Funzionante** con livello
testuale/visivo. La prova microfono non è stata eseguita; le evidenze e la
precondizione `GEV: ready` sono annotate nell'inventario.

## Fase 8 — Recap

- Meccanica: zoom incrementale (`camera_zoom`), ID 01.
- Fasi completate: 0–8 per il livello testuale/visivo; prova microfono
  trasversale rinviata.
- Test automatico Jarvis: `py_compile ui.py plugins/gev_plugin.py` superato;
  `pytest tests/test_gev_mcp_client.py -q` → 25 passed.
- Commit del blocco condiviso Jarvis: `46ded87`.
- Commit documentazione inventario Jarvis: `0572d74`.
- Commit storico GEV separato: `2bc902b`.
- Stato: **Funzionante (testuale/visivo)**.
- Prossima meccanica in coda: tilt camera, ID 02; il suo ciclo mantiene
  diagnosi, prova e aggiornamento inventario distinti dalle evidenze raccolte
  durante il test del blocco condiviso.
- Non iniziare il ciclo 05 finché non è registrata la revisione personale delle
  quattro evidenze camera richiesta per questa sessione.
