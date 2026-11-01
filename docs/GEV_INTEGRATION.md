## Limiti noti — lifecycle plugin

`stop_all(timeout=5.0)` esegue i lifecycle hook in sequenza
(`ThreadPoolExecutor(max_workers=1)`) con un timeout **globale** di 5 s.
Se un `stop()` si blocca:

- i future ancora pendenti vengono cancellati;
- il future già in esecuzione **non** è cancellabile: il suo thread
  continua in background finché la funzione non ritorna;
- `executor.shutdown(wait=False, cancel_futures=True)` non interrompe
  il thread in esecuzione.

Per il plugin GEV questo è accettabile perché `gev_plugin.stop()`
applica internamente `terminate()` → 5 s → `kill()`. Il limite vale
per eventuali plugin futuri con `stop()` bloccante: in quel caso
valutare `max_workers>1` o un meccanismo di kill forzato per-thread.

## Modifica alla whitelist dei guardrail

`core/guardrails.py` è stato esteso con `node` e `node.exe` in
`_ALLOWED_EXECUTABLES`. Motivazione: il plugin `gev` avvia God's Eye
View tramite il runtime Node portatile in `_gev-clone/.node/`, e il
guardrail blocca qualsiasi eseguibile non in whitelist prima di
`subprocess.Popen`.

Scope della modifica:

- autorizza qualunque `node` / `node.exe` invocato via subprocess da
  qualunque parte di Jarvis, non solo dal plugin GEV;
- la mitigazione è nel plugin: `plugins/gev_plugin.py` verifica che
  il path risolto di `node.exe` coincida con
  `_gev-clone/.node/node.exe` e rifiuta ogni altro percorso.

La modifica è minima e reversibile: rimuovere le due voci dal set
ripristina il comportamento precedente, al costo di disabilitare
l'avvio automatico di GEV.

### Perché node.exe e non npm

Su Windows `npm` è un wrapper `.cmd` che il guardrail rifiuta
(basename `npm.cmd` non in whitelist). Anche ammettendo `npm.cmd`
in whitelist, il wrapper invoca a sua volta `node.exe` come
subprocess, che sarebbe bloccato allo stesso modo. La soluzione
adottata è invocare direttamente `node.exe` con
`node_modules/npm/bin/npm-cli.js` per l'install e
`node_modules/vite/bin/vite.js` per il dev server. Così ogni
comando esterno passa dal solo eseguibile `node.exe`, autorizzato
in whitelist, e il plugin verifica che quel `node.exe` sia
esattamente quello del runtime portatile.

Come ulteriore fallback, `gev_plugin.py` registra `stop()` con `atexit`:
se il thread runner di Jarvis termina senza completare il proprio hook
di lifecycle, il processo GEV viene comunque terminato alla chiusura
normale dell'interprete. Questo fallback non si applica a terminazioni
forzate del processo, come `os._exit()` senza uno stop esplicito.

Su Windows, il processo Vite viene inoltre assegnato a un Job Object con
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, così il sistema termina il processo
GEV e i suoi discendenti se il processo Jarvis viene chiuso senza eseguire
gli hook Python.

## Limiti noti — preambolo Gemini Live

Quando Gemini decide di chiamare il tool `gev`, può emettere un preambolo
ottimista ("Certamente, signore, sto procedendo...") prima di ricevere
la risposta del tool. Se il tool fallisce o l'interfaccia non è pronta,
Gemini si corregge subito dopo. È un comportamento noto di Gemini Live,
cosmetico, non modificabile senza stravolgere la configurazione del
modello. Il plugin `gev` garantisce che **la conferma ottimistica
venga restituita solo dopo un invio riuscito** a `send_to_gev`; il
preambolo vocale è generato da Gemini indipendentemente da questo.

## Passo 5 — UI embed e bridge

### Architettura verificata nel codice

- `MainWindow` ospita una `QWebEngineView` in una pagina dedicata dello
  stack centrale; prima del caricamento mostra un placeholder
  (`../ui.py:2536-2557`).
- `open` carica `http://127.0.0.1:4173/` solo su richiesta. `open_tab`
  mostra la vista GEV nell'area centrale ampliata, nasconde temporaneamente
  il pannello contenuti inferiore e apre i pannelli GEV `data-panel` e
  `global-context-panel` quando la pagina segnala `gev:ready`. `hide_tab`
  torna all'HUD e ripristina visibilità e dimensioni precedenti senza
  scaricare GEV.
- La signal
  Qt `_gev_send_sig` inoltra i messaggi al thread della UI;
  `JarvisUI.send_to_gev()` valida e serializza il payload
  (`../ui.py:2427`, `../ui.py:2624`, `../ui.py:2732-2779`,
  `../ui.py:4668-4725`).
- Prima del caricamento viene registrato uno script `MainWorld` a
  `DocumentCreation`: imposta `window.GEV_EMBED_INLINE = true` e inoltra
  alla console i messaggi `gev:*` (`../ui.py:2560-2575`). GEV riconosce
  questa modalità tramite un confronto booleano stretto
  (`C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone\src\app\embed.js:36-46`).
- Jarvis carica la pagina con `?ui=panels`: GEV mostra Data Layers, Display,
  Location e Visual Presets, rimuove la maschera circolare e mantiene nascosti
  il dock vocale e POWER UP. Il bridge `gev:*` continua a dipendere
  separatamente da `GEV_EMBED_INLINE`; senza un parametro `ui`, l'embed resta
  nella modalità `globe` precedente. `ui=full` mostra invece l'interfaccia
  standalone completa.
- Nella prova live la viewport QWebEngine era 492×624 px CSS a DPR 2. In questa
  finestra Data Layers e Context sono limitati rispettivamente a 280 e 290 px;
  il rail Context scorre verticalmente. Location e Visual Presets condividono
  il dock a due colonne e aprono popover esclusivi, mantenuti dentro la
  viewport.
- Il dispatcher traduce le azioni in messaggi completi `gev:view`.
  Le risposte `gev:ready` e `gev:view-applied` vengono decodificate
  dall'override `javaScriptConsoleMessage`, passano per
  `MainWindow._on_gev_message()` e possono essere inoltrate al callback
  registrato con `JarvisUI.on_gev_message()`
  (`../ui.py:54-69`, `../ui.py:2838-2872`, `../ui.py:4573`, `../ui.py:4727`).
- Il protocollo del checkout GEV definisce `gev:view`,
  `gev:view-applied` e `gev:ready`; in modalità inline mittente e
  destinatario sono la stessa finestra
  (`C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone\src\app\embed.js:18-20`,
  `:253-300`).
- Le mappature layer/follow sono esplicite nel codice
  (`../ui.py:40-50`). GEV supporta follow per aircraft, military aircraft e
  satellite (`C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone\src\app\embed.js:22-26`,
  `C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone\src\view\index.js:30-50`);
  la UI Jarvis accetta solo `flight` e `satellite`, perciò il tipo `vessel`
  dichiarato dal plugin non è inoltrabile e produce un errore esplicito
  (`../ui.py:4710-4714`).

### Verifiche eseguite

- `py_compile` di `ui.py`: PASS; il bytecode di controllo è stato scritto
  fuori dal repository Jarvis.
- Harness isolato con payload fittizi: PASS per `layer`, `track`,
  `annotate`, `reset`, serializzazione, parsing di `gev:ready` e rifiuto
  esplicito del follow `vessel`. Questo verifica il codice Python del
  bridge, non il rendering WebEngine o l'esecuzione effettiva di GEV.
- Tentativo di smoke test Qt con piattaforma `offscreen`: processo
  terminato con codice `3221226505` prima delle asserzioni e senza output
  applicativo. La causa non è stata determinata; non è attribuita al
  bridge né considerata una verifica superata. Un test successivo nella
  finestra desktop reale ha invece verificato il caricamento WebEngine e
  il bridge, come descritto sotto.
- La diagnostica Pylance non riporta errori; segnala warning per simboli
  non usati in `ui.py`. Non è stato confrontato un baseline precedente.

### Esito verifica GUI Windows — 2026-10-04

- `send_to_gev()` accoda la signal Qt e non attende `gev:view-applied`.
  La risposta ottimistica del plugin indica quindi che l'invio alla UI è
  stato accettato, non che GEV abbia completato l'azione
  (`../ui.py:4725`, `../plugins/gev_plugin.py:682`). Il callback di
  risposta è predisposto per la gestione successiva.
- Sul desktop Windows non era presente un collegamento J.A.R.V.I.S.
  È stato creato `C:\Users\PC\Desktop\J.A.R.V.I.S.lnk`, puntato al
  `pythonw.exe` della `.venv`, con `main.py` e la directory del progetto
  come argomenti/percorso di lavoro. L'avvio del collegamento è stato
  verificato: la finestra `JARVIS — MARK LII` è apparsa e risultava
  reattiva.
- Dall'input testuale della finestra, Gemini ha attivato `gev`:
  `GEV: invio azione 'open'`, caricamento pagina e `GEV: ready`.
  In seguito `historical_map` ha caricato lo snapshot 1938 per la richiesta
  1939; `animate`, `stop` e `clear` hanno restituito esito positivo nei log.
  Lo screenshot della finestra ha mostrato il globo Cesium incorporato.
- Questa prova verifica il percorso testuale Gemini → plugin Jarvis →
  `QWebEngineView` → bridge GEV. Non è stata eseguita tramite microfono:
  il comando vocale effettivo con Gemini Live rimane non verificato.
- Un segnale `gev:ready` non ricevuto lascia la UI non pronta per le
  azioni diverse da `open`; il timeout di attesa non è implementato
  (`../ui.py:2732-2750`, `:2838-2844`, `:4668-4725`).
- Il layer satelliti, il test vocale con microfono e la chiusura mediante
  Ctrl+C con verifica della porta/processi **non sono stati verificati**
  durante quella prova. Il suo stato dei processi non costituisce una verifica
  dello stato corrente; il server Vite temporaneo usato nei test browser
  successivi è stato arrestato al termine dello smoke test.
  > Da verificare

## Passo 4c — client MCP locale

Jarvis avvia il server MCP stdio fornito dal checkout GEV con il medesimo
`node.exe` portatile e l'API locale Vite. La discovery MCP avviene dopo
`initialize` e `notifications/initialized`; le funzioni MCP vengono
pubblicate a Gemini come declaration separate `gev_mcp_*`. Il plugin
mantiene anche la funzione diretta `gev` per le azioni della UI.

Il client, l'adattatore schema e la serializzazione JSON-RPC si trovano in
[`../plugins/_gev_mcp_client.py`](../plugins/_gev_mcp_client.py); il ciclo
di vita e il routing dei tool sono in
[`../plugins/gev_plugin.py`](../plugins/gev_plugin.py). Il registro plugin
supporta le declarations dinamiche e inoltra la funzione namespaced alla
stessa implementazione plugin (`../core/plugin_loader.py`).

Nel checkout GEV verificato, `tools/list` ha restituito 30 funzioni. Non
sono esposte funzioni che GEV esclude esplicitamente dalla superficie MCP,
tra cui `plan_route`, `search_places`, `get_weather` e
`find_radio_stations`. La lista completa e il limite sono documentati in
[`GEV_MCP_INTEGRATION.md`](./GEV_MCP_INTEGRATION.md).

Verifiche: 9 test mirati (23 test nell'intera cartella `tests`) passati;
handshake live e conversione di tutti i 30 schemi in `google-genai`
passati; chiamata live di
`gev_mcp_get_recent_launches` conclusa restituendo una riga dati. La
verifica vocale con Gemini Live rimane distinta da queste prove API.

## Mappa storica — snapshot, scenari e bridge

Il plugin diretto `gev` accetta l'azione `historical_map` con `show`,
`animate`, `stop` e `clear`. Jarvis inoltra il comando all'app incorporata
tramite `gev:historical-map`; la risposta
`gev:historical-map-applied` riporta l'anno effettivamente caricato o
l'errore. L'overlay Cesium e il relativo lifecycle sono implementati nel
checkout GEV in `src/app/historicalMap.js`; l'aggancio al lifecycle applicativo
e al bridge è in `src/app/tools.js` e `src/app/embed.js`.

L'indice remoto viene validato e, se non raggiungibile, viene usato il file
locale `data/historical-index-fallback.json`. `listYears()` restituisce gli
anni accettati; per un anno senza snapshot viene usato lo snapshot più vicino
e il controller registra `requested_year` e `selected_year`. I GeoJSON remoti
sono conservati in IndexedDB per il fallback offline; l'intero archivio non è
incluso nel checkout (`src/app/historicalMap.js:94`, `:593`, `:674`).

La nuova superficie del plugin espone `historical_scenario` (parametri
`name`, `year` facoltativo), `historical_factions` (`scenario`, `year`),
`historical_events` (`scenario`, `year` facoltativo) e `historical_years`.
Sono inoltrati attraverso l'azione UI già consentita `historical_map`, con il
campo `type` impostato al corrispondente messaggio `gev:historical-*` e un ID
di correlazione. Il plugin registra `on_gev_message`, attende la risposta
corrispondente fino al timeout configurato e restituisce gli errori ricevuti;
`historical_years` restituisce i numeri degli anni
(`plugins/gev_plugin.py:545`, `:742`).

Le definizioni GEV si trovano in `data/factions.json` e `data/events.json`.
I colori e le date sono applicati dal controller Cesium; le classificazioni
per fazione sono configurazioni annuali curate, non proprietà verificate del
dataset GeoJSON. L'animazione temporale sceglie gli anchor di fazione più
vicini e non interpola geometrie tra gli snapshot. Vedere
[`../../../gods-eye-view-main/_gev-clone/docs/historical-maps.md`](../../../gods-eye-view-main/_gev-clone/docs/historical-maps.md)
per protocollo, limiti e scenari di verifica manuale.

**Verificato nel codice e nei test automatici di questa modifica:**

- GEV: parsing degli anni, incluso il filename BCE, elenco anni, selezione
  snapshot, fallback index/cache, materiali fazione aggiornati dal clock,
  avvio scenario, date giornaliere eventi e risposta correlata per `years`.
- Jarvis: validazione dei quattro comandi, payload personalizzati via
  `historical_map`, correlazione ID, timeout ed errori restituiti.
- Comandi eseguiti:
  `.\.node\node.exe --test src\app\historicalMap.test.mjs` nel checkout GEV;
  `.\.venv\Scripts\python.exe -m pytest tests\test_gev_mcp_client.py -q`
  nel checkout Jarvis.

**Verificato manualmente nel browser GEV:** `historical_years` ha restituito
54 anni; lo scenario `ww2` richiesto per il 1941 ha caricato lo snapshot 1938
con 531 entità e ha applicato i colori; il materiale Cesium dell'entità Italia
è passato da rosso nel 1941 a blu nel 1943; l'evento D-Day è risultato visibile
il 6 giugno 1944 e non visibile il giorno successivo. Portando il clock al
1942 e generando un tick Cesium, il controller ha sostituito lo snapshot 1938
con 1945; `clear` ha ripristinato anno, moltiplicatore e stato di animazione
precedenti.

**Non verificato manualmente in questa modifica:** collegamento dei quattro
messaggi alla finestra Jarvis QWebEngine, riconoscimento vocale e completamento
manuale dell'intero scenario in tempo reale. Il controller imposta un anno
simulato ogni 20 secondi. I test Python coprono il plugin e la correlazione
dei messaggi con callback controllate, non una sessione GUI integrata. AtlasPI
MCP non è stato installato né modificato; la relativa fase rimane opzionale e
non implementata.

> Da verificare: corrispondenza dei nomi delle entità GeoJSON con tutte le
> voci delle fazioni e accuratezza storica delle classificazioni annuali.

## Azioni camera Jarvis

Il plugin `gev` gestisce le azioni camera incrementali:

| Azione | Parametri | Effetto |
|---|---|---|
| `zoom` | `level: "in" \| "out"` oppure `altitude_m` | Dimezza/raddoppia l'altitudine corrente o imposta un'altitudine assoluta tramite `camera_zoom`. |
| `tilt` | `pitch_deg` da -90 a 0 | Aggiorna l'inclinazione con `camera_tilt`. |
| `rotate` | `heading_deg` da 0 a 360 | Aggiorna la rotazione orizzontale con `camera_rotate`. |
| `reset_camera` | nessuno | Ripristina il punto di vista globale con `camera_reset`. |

Il fly-to per nomi di luogo usa il tool MCP nativo `show_in_gods_eye_view`, che
risolve un'area e costruisce una vista. L'azione `gev.open_with_context` riusa
quel risultato per portare la camera embedded alle coordinate risolte e, per
le query storiche con anno esplicito, applica lo snapshot storico disponibile
più vicino e annota il tema. Non viene duplicata la risoluzione geografica del
GEV né viene aggiunta una nuova API al protocollo embedded.

I messaggi `camera_*` sono azioni interne del bridge Jarvis; l'UI aggiorna la
camera conservando gli altri campi della vista e invia a GEV il messaggio
completo `gev:view`. I campi camera e i relativi limiti sono verificati nello
schema GEV `src/view/index.js`; `gev:view` applica la posizione assoluta tramite
Cesium `camera.flyTo` (`src/app/embed.js`).

Le azioni incrementali non implementano pan o orbit continui. Questi
richiederebbero un'estensione futura del protocollo embed GEV.

**Validazione automatica:** `tests/test_gev_mcp_client.py` copre l'inoltro
incrementale di zoom, tilt, rotate e reset. Il fly-to è responsabilità del
tool MCP `show_in_gods_eye_view`. I test del bridge incrementale non
equivalgono a una verifica del rendering nella finestra QWebEngine o al
riconoscimento vocale tramite microfono.
