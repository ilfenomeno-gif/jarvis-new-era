# viewer3d

Globo olografico (Three.js) mostrato nello stack centrale di `ui.py`. `viewer.bundle.js` è generato da `src/viewer.js` e committato, così l'app non richiede Node né rete a runtime. Three.js è MIT (vedi `LICENSES.md`).

Rigenerare il bundle (richiede Node), da questa cartella:

```
npm ci
npm exec -- esbuild src/viewer.js --bundle --minify --format=iife "--define:import.meta.url=\"file:///three/examples/jsm/loaders/\"" --outfile=viewer.bundle.js
```

`package.json` e `package-lock.json` fissano Three.js, esbuild e
`@dimforge/rapier3d-compat` 0.19.3. Rapier incorpora il WASM nel bundle per
funzionare dalla pagina locale `file://`; il runtime non scarica dipendenze.
La licenza Apache-2.0 e la notice sono in `licenses/`.

API JS esposta come `window.jarvisViewer`: `flyTo(lat, lon)`, `addMarker(lat, lon, label)`, `clearMarkers()`, `spin(on)`, `setMaterialStyle('hologram'|'blueprint'|'realistic')`, `setPartInfo({parte: descrizione})` (tooltip al passaggio del mouse), `applyPhysics('drop'|'impulse')`, `getState()`.

Gli stati visuali sono definiti in `config/hud_states.json` e le durate in `config/hud_transitions.json`; PyQt6 interpola core, anelli, glow, waveform e particelle, mentre il viewer anima core, anelli e particelle con gli stessi parametri. Dopo aver modificato i JSON, eseguire `python -m core.registry_cli reload_hud_states` dalla cartella `Mark-LIV-main`: l'istanza attiva rileva il segnale su file e ricarica senza riavvio.

Il clipping del modello usa i suoi bounds locali e rimane solidale alla trasformazione quando il modello ruota. Il renderer abilita lo stencil buffer per chiudere la superficie tagliata; `set_clipping` accetta `axis=x|y|z|off` e `position=0..1` (predefinito 0.5). Lo spin automatico resta disattivato finché il clipping è attivo.


HDRI `hdr/studio.hdr`: Poly Haven `studio_small_03` 1k, licenza CC0 (usato da `realistic` per riflessi PBR).

Decoder Draco (Apache-2.0) in draco/, copiati da 	hree/examples/jsm/libs/draco/gltf/; il decoder Meshopt è incluso nel bundle. Il viewer carica solo risorse locali sotto models/ (URL esterni bloccati).

Fisica Rapier: `applyPhysics('drop'|'impulse')` agisce sul modello caricato,
con collider cuboide semplificato, pavimento, gravità e impulso verticale
limitato. `explodeModel(true)` interrompe e rimuove il body, ripristina la posa
iniziale e poi anima i componenti; applicare fisica a un modello esploso prima
lo riassembla. La fisica non simula collisioni tra i componenti interni del PC.
