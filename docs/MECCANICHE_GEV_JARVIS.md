# Inventario meccaniche GEV e integrazione Jarvis

Questo inventario distingue le capacità del prodotto GEV da quelle invocabili
da Jarvis. Un comando scritto come esempio è una frase naturale suggerita per
Gemini, non una grammatica rigida né la garanzia che il modello selezioni sempre
lo stesso tool.

## Legenda dello stato

- **Funzionante** — la capacità è stata provata nel percorso indicato (test
  automatico o prova manuale). Per i feed live, questo non garantisce
  disponibilità continua del provider.
- **Semi funzionante** — il codice/bridge è presente, ma la prova è parziale,
  la feature dipende da chiavi o provider, oppure manca la verifica end-to-end
  nella UI.
- **Non funzionante in Jarvis** — non esiste un'azione Jarvis/bridge per
  controllare quella meccanica. Può comunque funzionare nel GEV autonomo.

**Importante:** “non funzionante in Jarvis” non significa che il codice GEV sia
guasto. Jarvis espone solo una parte delle azioni GEV.

**Limite dell'embed a pannelli:** le modifiche fatte con il mouse nei pannelli
GEV non vengono sincronizzate nello stato conservato da Jarvis. Un successivo
`reset` inviato da Jarvis può quindi sovrascrivere layer o altre impostazioni
scelte nell'interfaccia GEV.

## Sintesi dell'integrazione

| Nome | Descrizione | Comando Jarvis suggerito | Verifica e stato |
|---|---|---|---|
| Apertura GEV | Avvia/carica il globo nella finestra integrata. | “Jarvis, apri God's Eye View.” | **Funzionante** — UI testuale ha restituito `gev:ready` in una prova manuale. |
| Scheda GEV ampia | Mostra il globo nell'area centrale ampliata di Jarvis con `DATA LAYERS`, `DISPLAY`, `LOCATION` e `VISUAL PRESETS` utilizzabili. Il contesto resta disponibile; Location e Visual Presets sono schede inferiori che si aprono una alla volta. Voce GEV e POWER UP sono nascosti, e la maschera circolare non viene disegnata. | “Jarvis, apri la scheda di God's Eye View con tutti i menu.” Per tornare: “Jarvis, chiudi la scheda GEV.” | **Convalidato live in QWebEngine** — `open_tab` ha caricato `?ui=panels`, ricevuto `gev:ready` ed espanso Data Layers, Display e Context; disclosure e preset rispondono ai click, ricerca Location visibile e tray inferiori esclusivi. La viewport provata era 492×624 px CSS a DPR 2: Data Layers 280 px, Context 290 px con scroll verticale. Maschera, voce GEV e POWER UP assenti. Evidenze: [Data Layers + Display](../../../GEV-Jarvis-Project/impl/25-gev-panels-display.png) e [Data Layers + Context](../../../GEV-Jarvis-Project/impl/25-gev-panels-context.png). Verifiche non incluse: attivazione di un layer con provider esterno e prova microfono. `hide_tab` ripristina schermata e dimensione. |
| Vista verso un luogo (fly-to) | Cerca l'area e prepara una vista centrata sul luogo attraverso il tool MCP nativo GEV. | “Jarvis, vai a Roma.” | **Funzionante lato dispatch** — prova testuale ha chiamato `show_in_gods_eye_view`; il log MCP lo conferma. Il fly-to non è un'azione del plugin `gev`; il rendering/camera non è stato verificato visivamente in quest'ultimo test. |
| Zoom incrementale | Dimezza o raddoppia l'altitudine della camera corrente. | “Jarvis, zoomma dentro.” / “Zoomma fuori.” | **Funzionante (testuale; screenshot live acquisito)** — dopo `GEV: ready`, la UI ha dispatchato `camera_zoom` per `in` e `out`; test automatici: 25 passati. Screenshot in `C:\Users\PC\Downloads\GEV-Jarvis-Project\impl\01-zoom-visivo.png`; revisione personale richiesta ancora aperta. Il microfono non è stato provato. |
| Inclinazione camera | Imposta `pitch_deg` nell'intervallo -90..0. | “Jarvis, inclina lo sguardo verso il basso.” | **Funzionante (testuale; screenshot live acquisito)** — log UI: `camera_tilt`, `pitch_deg=-45`. Screenshot in `C:\Users\PC\Downloads\GEV-Jarvis-Project\impl\02-tilt-visivo.png`; revisione personale richiesta ancora aperta. Il microfono non è stato provato. |
| Rotazione camera | Imposta `heading_deg` nell'intervallo 0..360. | “Jarvis, ruota la vista di 90 gradi.” | **Funzionante (testuale; screenshot live acquisito)** — log UI: `camera_rotate`, `heading_deg=90`. Screenshot in `C:\Users\PC\Downloads\GEV-Jarvis-Project\impl\03-rotate-visivo.png`; revisione personale richiesta ancora aperta. Il microfono non è stato provato. |
| Reset camera | Reimposta camera globale senza usare il reset completo del plugin. | “Jarvis, usa il plugin GEV per resettare solo la camera.” | **Funzionante (testuale; screenshot live acquisito)** — `camera_reset` ripristina la vista globale. Screenshot in `C:\Users\PC\Downloads\GEV-Jarvis-Project\impl\04-camera-reset-visivo.png`; revisione personale richiesta ancora aperta. La frase generica “torna alla vista globale” ha selezionato il reset completo `reset`. Il microfono non è stato provato. |
| Pan / orbit continui | Movimento incrementale laterale o orbitale della camera. | Nessun comando Jarvis disponibile. | **Non funzionante in Jarvis** — il protocollo embed `gev:view` è una vista assoluta; manca un messaggio bridge per pan/orbit continui. |
| Attivazione/disattivazione layer | Il bridge Jarvis mappa sei alias di layer a ID GEV. | “Jarvis, attiva il layer satelliti.” (sostituire col layer desiderato) | **Funzionante per i sei layer elencati sotto** — bridge verificato via prove manuali precedenti; dati e copertura dipendono dai provider. |
| Tracking volo | Seleziona e segue un aeromobile identificato. | “Jarvis, traccia il volo `<callsign/ID>`.” | **Funzionante** — tracking testuale di un volo verificato in una prova precedente. Il dato può non essere trovato o essere stale. |
| Tracking satellite | Segue un satellite indicato dal suo ID. | “Jarvis, traccia il satellite `<NORAD ID>`.” | **Funzionante** — bridge e query satellitare verificati in prove precedenti; dipende dal catalogo/caricamento. |
| Annotazione punto/testo | Aggiunge un'etichetta a coordinate date. | “Jarvis, annota `<testo>` a latitudine `<lat>` e longitudine `<lon>`.” | **Funzionante per etichette puntuali** — bridge provato. Disegni vocali complessi, poligoni e misurazioni non sono esposti dalla singola azione Jarvis `annotate`. |
| Reset completo vista | Ripristina vista e stato della pagina secondo la logica Jarvis esistente. | “Jarvis, resetta la vista GEV.” | **Funzionante** — azione `reset` verificata in prove precedenti. È più ampia di `reset_camera`: può azzerare anche layer, follow e annotazioni. |
| Mappe storiche | Anni, scenari, fazioni, eventi e animazione dei confini storici. | “Jarvis, elenca gli anni storici disponibili”; “carica lo scenario WWII 1941”; “anima i confini dal 1939 al 1945”; “ferma la riproduzione”. | **Funzionante nel test manuale testuale precedente** per anni, scenario/snapshot, eventi, fazioni e animazione/stop. Verifica di una sessione vocale tramite microfono non effettuata. |
| Tool MCP di ricerca | Il plugin rende disponibili tool aggiuntivi `gev_mcp_*` per dati e query GEV. | “Jarvis, cerca …” seguito dalla domanda (ad esempio voli o terremoti). | **Semi funzionante** — catalogo MCP connesso e query selezionate provate; risultati e copertura dipendono da rete, chiavi e provider. Non equivale al controllo completo dell'interfaccia GEV. |

## Layer dati e mappa

Il README GEV dichiara 19 layer/fonti e indica che 17 hanno un percorso
keyless. Conteggi come “11.000 voli” o “838 satelliti” sono descrizioni del
catalogo/prodotto, non una garanzia del numero restituito ad ogni avvio.

| Nome meccanica/layer | Descrizione | Comando Jarvis | Verifica e stato |
|---|---|---|---|
| Map Stack / basemap | Seleziona lo stack cartografico: Esri, OSM, Google Photorealistic 3D e stack ospitati da Cesium ion, secondo configurazione e disponibilità delle chiavi. È distinto dal fly-to/geocoder. | Nessun comando Jarvis verificato per cambiare provider. Nella voce nativa GEV è documentata la richiesta “Switch to OSM.” | **Non funzionante in Jarvis** per il cambio stack; GEV ha `set_map_stack`. Supporto/provider e disponibilità dei singoli stack dipendono dalla configurazione. |
| Live Flights | Posizioni ADS-B/OpenSky con fallback e informazioni di rotta quando disponibili. | “Attiva/disattiva il layer voli.” | **Funzionante come toggle Jarvis**; feed live **semi funzionante** perché copertura, quota e provider variano. |
| Military Flights | Traffico aereo militare reso come layer distinto in GEV. | Nessun comando Jarvis per il layer militare. | **Non funzionante in Jarvis** — `military` non è tra le sei chiavi di `_GEV_LAYERS`; GEV autonomo lo documenta come layer. |
| Live Vessels / AIS | Posizioni delle navi da feed AIS. | “Attiva/disattiva il layer navi.” | **Funzionante come toggle Jarvis**; **semi funzionante come feed** per dipendenza da credenziali AIS e copertura geografica variabile. |
| Satellites | Catalogo orbitale, classi, orbite propagate e passaggi. | “Attiva il layer satelliti”; “traccia il satellite `<ID>`.” | **Funzionante** — layer/tracking provati in precedenza; disponibilità effettiva dipende da catalogo e caricamento. |
| Earthquakes | Eventi sismici recenti, fonte USGS. | “Attiva il layer terremoti.” | **Funzionante come toggle**; feed remoto non garantito in ogni momento. |
| Traffic | Traffico simulato su strade reali; flussi TomTom possono fornire velocità/congestione live. | Nessun comando Jarvis per il layer traffic. | **Non funzionante in Jarvis** — non mappato dal bridge; la simulazione GEV non rappresenta posizioni live individuali. |
| CCTV Mesh | Telecamere pubbliche con posizione e visualizzazione spaziale; posa/orientamento possono essere stime. | “Attiva il layer CCTV.” | **Semi funzionante** — il toggle Jarvis esiste e il feed ha risposto in prove; feed/frame non sempre disponibili e geometria non certificata per ogni camera. |
| Viewshed e calibrazione CCTV | Il pannello CCTV separa il toggle telecamere dal toggle `COVERAGE`; il controllo `ADJUST` apre la calibrazione spaziale con gizmo/maniglie. Lo schema vocale contempla anche la modalità `viewshed`. | Nessun comando Jarvis per coverage, viewshed o calibrazione. In GEV UI: “CCTV ON”, poi `COVERAGE` e `ADJUST`; le parole non sono qui certificate come comandi vocali. | **Non funzionante in Jarvis**; controlli e schema sono presenti in GEV, ma nessun test manuale camera-per-camera è documentato. |
| Mapped ALPR cameras | Posizioni/tag di telecamere mappate; non è un feed di targhe o video ALPR. | Nessun comando Jarvis per il layer ALPR. | **Non funzionante in Jarvis** — layer non incluso nella mappa bridge. |
| Radio | Radio Browser alimenta stazioni geolocalizzate; il pannello/UI offre selezione e tuner analogico. Il README descrive fino a 750 stazioni: è il limite/dato dichiarato dal progetto, non un conteggio live verificato. | Nessun comando radio Jarvis; il plugin non ha azione radio e `find_radio_stations` non è offerto dal catalogo MCP Jarvis. | **Non funzionante in Jarvis**. Il controllo nativo è documentato; riproduzione audio/stazioni in questa sessione non convalidata. |
| Transit | Bus, tram, metro, treni e traghetti da feed GTFS-Realtime supportati. | Nessun comando layer Jarvis dedicato. | **Non funzionante in Jarvis** per il toggle; disponibilità dei feed è specifica dell'operatore. |
| Bikeshare | Disponibilità delle stazioni via GBFS. | Nessun comando layer Jarvis dedicato. | **Non funzionante in Jarvis** per il toggle. |
| Directions / routing | Percorsi stradali a piedi, in auto o bici; GEV può disegnare e animare il percorso. | “Jarvis, pianifica un percorso da A a B” può invocare un tool MCP di routing; nessun comando Jarvis verificato per disegnare e poi pilotare la camera lungo il percorso. | **Semi funzionante** — routing MCP disponibile; fly-route e percorso visibile non verificati end-to-end in Jarvis. |
| Active Fires / FIRMS | Rilevazioni di incendi NASA, con latenza e copertura proprie del feed. | “Attiva il layer incendi.” | **Funzionante come toggle**; feed **semi funzionante** e condizionato dalla chiave FIRMS/configurazione. |
| Space Missions / launches | Lanci recenti e traiettoria ricostruita, indicata come stima. | Possibile domanda su lanci tramite MCP; nessun comando Jarvis verificato per avviare/scrubbare replay. | **Semi funzionante via query MCP**; controllo visuale/replay non esposto dal bridge Jarvis. |
| Mapped Installations | Siti militari da mappatura comunitaria, incompleti per definizione. | Possibile query MCP; nessuna azione layer Jarvis dedicata. | **Semi funzionante solo come interrogazione MCP**; non è un inventario completo né un toggle Jarvis. |
| Meteo: vento, osservazioni e timeline | Wind mostra previsione del flusso a 10 m da NOAA GFS o ECMWF IFS. Radar pioggia, nubi satellitari e densità dei fulmini usano una timeline osservativa condivisa nel pannello WEATHER, con step indietro, Play e Latest. I dati osservati hanno prodotti, coperture e ritardi diversi; la timeline non è l'animazione storica dei confini. | Nessun comando Jarvis verificato per selezione layer, seek, playback o velocità della timeline meteo. | **Non funzionante in Jarvis** per i controlli visuali/timeline; GEV documenta le feature. La disponibilità e granularità del dato dipendono dalla fonte. |
| Cyclones | Advisory, traiettorie previste e coni d'incertezza NOAA NHC/CPHC. | Nessun comando layer Jarvis dedicato. | **Non funzionante come controllo visuale Jarvis**; feature GEV dipendente dall'aggiornamento del provider. |
| Infrastruttura statica | Dataset inclusi per datacenter, dighe e cavi sottomarini. | Domande di conteggio/ricerca possono usare MCP; nessun toggle layer Jarvis dedicato. | **Semi funzionante via query**; la visualizzazione non è controllata dal bridge layer Jarvis. |

### Layer effettivamente mappati dal bridge Jarvis

Gli alias accettati sono esattamente `flights`, `vessels`, `satellites`,
`earthquakes`, `fires`, `cctv` ([`ui.py`, `_GEV_LAYERS`](../ui.py)).
“Attiva `<alias>`” e “disattiva `<alias>`” sono le forme suggerite.
L'azione `layer` richiede anche `enabled: true/false`; alias non supportati
vengono rifiutati dalla UI anziché inoltrati.

## Controlli visuali e strumenti nativi GEV

Questa sezione elenca capacità GEV che **non** vanno scambiate per azioni
Jarvis. Le frasi sono comandi da provare nella voce nativa GEV o nella sua UI,
non comandi garantiti per il plugin Jarvis.

| Nome | Descrizione | Comando Jarvis | Verifica e stato |
|---|---|---|---|
| Visual styles | Preset `normal`, `retro`/CRT, `surveillance`/NVG, `thermal`/FLIR, `anime`, `noir`, `snow`. | Nessun comando Jarvis per selezionare lo stile. | **Non funzionante in Jarvis**; preset presenti nello schema voice GEV. |
| Detection overlay | Overlay di rilevamento con controllo separato di attivazione, modalità (`sparse`, `balanced`, `dense`), `densityPct` (percentuale), strategia di allocazione e altri parametri. La percentuale non è un semplice interruttore on/off. | Nessun comando Jarvis per detection. La voce nativa GEV documenta “Set detection density to fifty percent.” | **Non funzionante in Jarvis**; lo schema e il dispatcher nativi GEV espongono `set_detection`, incluso `densityPct`. |
| Military HUD / layout | HUD con telemetry e layout selezionabili. | Nessun comando Jarvis dedicato. | **Non funzionante in Jarvis**; non confondere il layout HUD con un layer dati. |
| Cockpit view | Camera a bordo del contatto aereo tracciato. | Il tracking volo è disponibile; non c'è un'azione Jarvis per entrare/uscire dal cockpit. | **Semi funzionante** — GEV documenta `control_cockpit`; Jarvis non inoltra quel controllo. |
| Contacts mode | Roster di contatti attorno al target e passaggio tra contatti. | Nessun comando Jarvis dedicato. | **Non funzionante in Jarvis**. |
| Global Context | Composizione temporanea dei layer di contesto con ritorno alla vista precedente. | Nessun comando Jarvis dedicato. | **Non funzionante in Jarvis**. |
| 3D Hangar: modalità modelli | La logica flotta distingue `proximity` (contatti più vicini entro il relativo cap) e `all` (contatti in vista entro il cap dedicato). Sono due regimi, non due classi di aeromobile. | Nessun comando Jarvis verificato per passare tra `proximity` e `all`. | **Non funzionante in Jarvis**; i due regimi e i rispettivi limiti sono presenti nel codice GEV (`queries.js`, `policy.js`), non verificati come controllo vocale/UI manuale in questa sessione. |
| Scene Director: record e shot | Gestione scene e shot: creazione/eliminazione, `CAPTURE SHOT` per registrare la vista corrente, `UPDATE SHOT` per aggiornare lo shot selezionato. | Nessun comando Jarvis dedicato; “Play Orbital Watch” nel README è un esempio di voce nativa GEV, non dispatch Jarvis. | **Non funzionante in Jarvis** per il Director; controlli UI e implementazione GEV presenti, test manuale dell'interfaccia non attestato qui. |
| Scene Director: playback | `START`, `STOP` e `NEXT` avviano/interrompono/avanzano la riproduzione della scena; il codice descrive inoltre l'uscita con Escape durante il playback. | Nessun comando Jarvis dedicato. | **Non funzionante in Jarvis**; comportamento nativo individuato nel codice, non verificato manualmente in questa sessione. |
| Scene Director: import/export | Il pannello offre `EXPORT PRESETS`, `IMPORT` e `RUN LOG`; il codice di sharing gestisce anche export/import di documenti o bundle scena. Sono operazioni del Director, distinte dal link condivisibile dell'app. | Nessun comando Jarvis verificato per importare/esportare scene o run log. | **Non funzionante in Jarvis**; UI e codice GEV presenti, flusso manuale non convalidato qui. |
| Share Links | Il gestore Share Links serializza nello URL hash camera, stile e stato supportato dell'app e offre una funzione per copiare il link. Non equivale all'export/import JSON delle scene del Director. | Nessun comando Jarvis verificato per generare o copiare Share Links. Il fly-to MCP “vai a `<luogo>`” non crea un link né esporta una scena. | **Non funzionante in Jarvis**; funzione GEV distinta dal Scene Director, non provata end-to-end qui. |
| Reset globe | Ripristino della visuale globale. | “Jarvis, usa il plugin GEV per resettare solo la camera.” | **Funzionante (testuale/visivo)** via `reset_camera`; verificato dopo zoom. “Torna alla vista globale” ha selezionato invece il reset completo `reset`. Prova microfono non eseguita. |
| Ricerca/geocoding GEV | Risoluzione di luoghi; il tool MCP di vista accetta un'area oppure coordinate camera. | “Jarvis, vai a Roma.” | **Funzionante lato dispatch** — prova manuale ha chiamato `show_in_gods_eye_view`; la verifica della camera risultante non è stata completata. |
| Voce nativa GEV | Le azioni GEV comprendono navigazione, annotazioni, query, radio, CCTV e scene. | Non è un comando del plugin Jarvis; va provata nel microfono/modalità vocale GEV. | **Semi funzionante come feature GEV documentata/testata**; la sua integrazione diretta con il microfono Jarvis non è verificata e le superfici voice/MCP sono distinte. |

### Meccaniche aggiuntive e distinzioni

Queste righe completano le voci aggregate sopra. “Nessun comando Jarvis”
indica che non risulta un'azione specifica nel bridge/plugin documentato; un
esempio di comando GEV nativo non va interpretato come prova che Jarvis lo
inoltri.

| Nome | Descrizione | Comando Jarvis | Verifica e stato |
|---|---|---|---|
| AI HUD Summary | Riepilogo d'intelligence in cinque parole del contesto/vista corrente; il README dice che si rigenera mentre l'utente si muove e usa la stessa chiave OpenAI della voce. Il testo “cinque parole” e il comportamento sono dichiarazioni del README, non misurazioni di latenza/frequenza. | Nessun comando Jarvis: è HUD GEV. | **Non funzionante come controllo Jarvis**; feature descritta nel README e implementazione HUD presente. Nessuna prova live dedicata registrata in questa verifica. |
| Celestial mode / ring | Toggle display per il ring celeste a schermo intero, con sole/luna secondo l'implementazione GEV. Il controllo UI è distinto dalle mappe basemap. | Nessun comando Jarvis verificato. In GEV UI: toggle `Celestial`. | **Non funzionante in Jarvis**; controllo e logica GEV presenti, prova visuale manuale non attestata qui. |
| POWER UP / gestione API keys | Chip/dialog in-app per configurare o rimuovere le chiavi provider. Il sorgente lo limita al dev server; non è la stessa cosa che usare una chiave già presente nell'ambiente. | Nessun comando Jarvis. | **Semi funzionante in GEV dev UI** — componente e operazioni di salvataggio sono nel codice; non è disponibile come meccanica del bridge Jarvis e non è stata provata qui su un'istanza. |
| Ricerca luoghi nella UI GEV | Campo `Search any location...` accetta nomi o coordinate dalla barra LOCATION. È distinto sia dal geocoder endpoint sia dal tool MCP `show_in_gods_eye_view`. | Nessun comando Jarvis per interagire con il campo UI; per il fly-to Jarvis usare il tool MCP già documentato. | **Presente nella UI GEV**; la ricerca da Jarvis è una strada separata e non equivale all'uso del campo. Prova UI manuale della barra non attestata qui. |
| TR-3B Easter egg | Un contatto tracciato può essere convertito in TR-3B dal chip contestuale; la conversione è temporanea di sessione e non equivale a un velivolo reale del feed. | Nessun comando Jarvis verificato. | **Presente nel codice GEV**; il codice lo identifica come Easter egg. Attivazione manuale in UI non verificata in questo inventario. |
| Janet 27 | Meccanica indicata nelle note di audit come Easter egg/extra associato a TR-3B. | > Da verificare | > Da verificare: non è stato individuato un riscontro puntuale nel codice/README consultato; non se ne descrivono qui comportamento o comando. |
| `move_camera` nativa GEV | Tool voice nativo con motion `orbit`, `pan`, `tilt`, `rotate` e `stop`. Non è il messaggio embed `gev:view` né le quattro azioni incrementali `camera_*` di Jarvis. | Nessun comando del plugin Jarvis verificato per `move_camera`; nella voce nativa GEV è disponibile il tool. | **Verificato nel codice GEV**, ma **non integrato nel bridge Jarvis**. L'assenza di Jarvis non significa che la capacità manchi a GEV. |
| `ask_about` / world knowledge | La sessione di audit segnala una domanda vocale generale (esempio: “Tell me about Rotterdam”). `ask_about` non è stato trovato come nome di azione dedicato nello schema voice consultato. | > Da verificare | > Da verificare: distinguere una risposta conversazionale generale dalla presenza di un tool `ask_about`; non è verificato un dispatch omonimo né un comando Jarvis. |

### Fonti puntuali per le meccaniche aggiunte

- AI HUD Summary: `README.md:238`; ciclo e chiamata al servizio in
  `src/hud.js:280`, `src/hud.js:715-739`.
- Detection density: `src/voice/actionSchemas.js:339-357`,
  `src/voice/gevActions.js:1072-1084`; esempio vocale in `README.md:274`.
- Meteo/timeline: `README.md:310`; clock e playback in
  `src/layers/weather/clock.js:67-192`.
- Map Stack: `README.md:290`, `src/voice/actionSchemas.js:362`,
  `src/voice/gevActions.js:1087-1092`.
- POWER UP: `src/keySetup.js:4-8`, `src/keySetup.js:20-24`,
  `src/ui/templates/provider-settings.html:1-7`; il template segnala il
  vincolo dev-server.
- Location bar: `src/ui/templates/command-dock.html:68-93`.
- Celestial: `src/ui/templates/display-controls.html:151-153`,
  `src/ui/applicationShell.js:398-400`, `src/ui/applicationShell.js:1197-1207`.
- CCTV: `src/ui/templates/layer-panels.html:32-52`,
  `src/voice/actionSchemas.js:448`.
- Modelli: `src/layers/flights/queries.js:285-318`,
  `src/layers/flights/policy.js:69-73`.
- Scene Director: `src/ui/templates/layer-panels.html:74-101`,
  `src/scenes/director.js:1666`; import/export in `src/scenes/sharing.js:326`,
  `src/scenes/sharing.js:376`.
- Share Links: `src/sharelink.js:15-17`, `src/sharelink.js:508-537`.
- Radio: `README.md:299`, `src/voice/actionSchemas.js:465`,
  `src/tools/surfaces.js:46` (`find_radio_stations` escluso dalla superficie MCP).
- TR-3B: `docs/CURRENT-STATE.md:4071-4073`,
  `src/data/tr3bRegistry.js:25-37`, `src/voice/gevActions.js:2805-2821`.
- `move_camera`: `src/voice/actionSchemas.js:737-746`,
  `src/voice/gevActions.js:999-1009`.

## Comandi storici Jarvis

| Nome | Descrizione | Comando Jarvis suggerito | Verifica e stato |
|---|---|---|---|
| Elenco anni | Restituisce gli anni disponibili dall'indice storico. | “Jarvis, elenca gli anni storici disponibili.” | **Funzionante** in prova testuale precedente. |
| Scenario storico | Carica scenario, snapshot, fazioni/eventi previsti dal controller. | “Jarvis, carica lo scenario Seconda Guerra Mondiale 1941.” | **Funzionante** in prova testuale precedente; l'anno richiesto può selezionare lo snapshot disponibile più vicino. |
| Fazioni storiche | Applica palette di fazione per scenario/anno. | “Jarvis, applica le fazioni WWII 1943.” | **Funzionante** in prova testuale/browser precedente; accuratezza storica delle classificazioni resta curatoriale. |
| Eventi storici | Mostra gli eventi dello scenario, eventualmente filtrati per anno. | “Jarvis, carica gli eventi WWII 1944.” | **Funzionante** in prova testuale precedente. |
| Animazione confini | Riproduce una serie di snapshot storici. | “Jarvis, anima i confini dal 1939 al 1945”; “ferma la riproduzione.” | **Funzionante** in prova testuale precedente; snapshots discreti, non interpolazione continua dei confini. |

## Comandi Jarvis supportati dal plugin `gev`

| Nome | Descrizione | Esempio comando | Stato |
|---|---|---|---|
| `open` | Apre/carica GEV. | “Apri God's Eye View.” | **Funzionante**, test manuale precedente. |
| `track` | Segue `flight` o `satellite` con identificativo. | “Traccia il satellite `<NORAD ID>`.” | **Funzionante**, prova precedente; vessel non supportato come target nel bridge. |
| `layer` | Attiva/disattiva i sei alias ammessi. | “Attiva il layer terremoti.” | **Funzionante** per alias ammessi. |
| `reset` | Reset completo della vista Jarvis. | “Resetta la vista GEV.” | **Funzionante** in prova precedente. |
| `annotate` | Etichetta puntuale a lat/lon. | “Annota `<testo>` a `<lat>`, `<lon>`.” | **Funzionante** per marker/label; non è il whiteboard GEV completo. |
| `historical_*` | Anni, scenario, fazioni, eventi, animazione. | Esempi nella tabella storica. | **Funzionante** nelle prove manuali testuali precedenti. |
| `zoom`, `tilt`, `rotate`, `reset_camera` | Modifiche camera incrementali tramite azioni bridge `camera_*`. | Esempi nella sintesi. | **Funzionante (testuale/visivo per le quattro azioni)** — prove nella finestra integrata e risposte UI registrate; 25 test mirati passati. Prova microfono trasversale non eseguita. |
| `fly_to` | Non è più un'azione del plugin per evitare collisione con il tool MCP. | Usare “vai a `<luogo>`”, che deve chiamare `show_in_gods_eye_view`. | **Non applicabile al plugin**; il dispatch MCP è stato osservato manualmente per Roma. |
| `pan` / `orbit` | Movimento camera continuo. | Nessuno nel plugin Jarvis. | **Non funzionante in Jarvis**. |

## Evidenze e limiti

- Verifica di completezza delle voci aggiuntive (2026-10-04): AI HUD Summary,
  Celestial mode, POWER UP, timeline meteo, detection density, TR-3B/Janet 27,
  modalità modelli `proximity`/`all` e ricerca luoghi UI sono già elencati
  nelle sezioni supplementari e nelle fonti puntuali qui sotto. Non sono state
  replicate nella sintesi principale; Janet 27 resta `Da verificare`.
- Il bridge layer Jarvis è definito in `ui.py` nella mappa `_GEV_LAYERS`; i
  controlli camera `camera_zoom`, `camera_tilt`, `camera_rotate`,
  `camera_reset` aggiornano la vista e inviano `gev:view`.
- Le azioni camera incrementali hanno superato
  `pytest tests/test_gev_mcp_client.py -q` (25 test dopo l'eliminazione del
  dispatch fly-to duplicato). Inoltre le prove testuali nella finestra
  integrata hanno prodotto `camera_zoom` in/out, `camera_tilt` con pitch -45,
  `camera_rotate` con heading 90 e `camera_reset`; il globo ha mostrato
  variazioni visive coerenti con le azioni. Il dispatcher/documentazione
  testati sono nel commit Jarvis `46ded87`. Nessuna misura numerica
  dell'altitudine è stata raccolta.
- La finestra deve aver restituito `GEV: ready` prima di inviare controlli
  camera. Prima di `ready` il comando zoom è fallito; dopo `ready` lo stesso
  comando ha raggiunto il bridge.
- Il comando generico “torna alla vista globale” è stato interpretato come
  reset completo (`reset`), non come `reset_camera`. Per provare il reset
  incrementale usare una frase esplicita che nomini la sola camera.
- La prova manuale più recente “Jarvis, vai a Roma” ha prodotto nel log GEV
  una chiamata MCP `show_in_gods_eye_view`. Il log conferma la selezione del
  tool, non da solo l'esito visivo della camera.
- Le prove manuali precedenti di layer, tracking, annotazione e storico sono
  prove testuali/UI, non prove del microfono reale.
- Errori occasionali di rete/provider non dimostrano un bug persistente del
  client; API key, quote, cache e copertura geografica condizionano alcuni feed.
- Lo stato “Funzionante (testuale/visivo)” non certifica l'uso vocale: la prova
  microfono trasversale è ancora da eseguire.
- **Gate di pubblicazione — licenza del dataset storico:** il `package.json`
  GEV dichiara MIT per il progetto/codice, mentre `DATA_SOURCES.md` dichiara
  che l'indice fallback copiato da `aourednik/historical-basemaps` resta sotto
  GPLv3 ed è accompagnato dal testo licenza. Questo documenta la provenienza,
  ma non decide la compatibilità/strategia di redistribuzione. Prima di push
  o pubblicazione occorre una decisione verificata su permanenza nel repo,
  download a runtime o termini separati. **Esito: `> Da verificare`; nessuna
  conclusione legale è registrata.**
- La revisione personale degli screenshot camera richiesti per i cicli 01–04
  non è ancora attestata. Non procedere alla meccanica 05 finché tale controllo
  non è registrato.

## Fonti nel workspace

- Repository Jarvis: `plugins/gev_plugin.py`, `ui.py`,
  `tests/test_gev_mcp_client.py`, `docs/GEV_INTEGRATION.md`.
- Repository GEV: `README.md`, `DATA_SOURCES.md`,
  `src/voice/actionSchemas.js`, `src/voice/gevActions.js`,
  `src/tools/surfaces.js`, `src/app/embed.js`, `src/view/index.js`,
  `src/app/historicalMap.js`, `public/models/README.md`.
- Nota di integrazione: [GEV_INTEGRATION.md](./GEV_INTEGRATION.md).
