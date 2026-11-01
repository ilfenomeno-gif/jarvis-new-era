---
name: hud-ui
description: Crea HUD e interfacce animate (2D canvas, 3D, SVG, CSS, WebGL) per app desktop e web: anelli di telemetria, molecole/particelle, pannelli chat, stati dell'assistente, effetti sci-fi. Usala quando l'utente chiede HUD, dashboard futuristiche, UI per assistenti AI, animazioni 2D/3D, indicatori di stato o qualsiasi interfaccia in stile cockpit/Jarvis.
---

# Skill: HUD / UI animate

## 0. Prima di scrivere codice
1. Definisci in una riga: **soggetto** (cosa mostra), **utente** (chi lo guarda e a che distanza), **lavoro principale** (cosa deve capire in 1 secondo).
2. Scegli **un solo elemento memorabile** (es. molecole al centro). Tutto il resto resta sobrio.
3. Scegli la tecnologia con la tabella:

| Serve | Usa | Perché |
|---|---|---|
| Molti elementi animati, glow, anelli, particelle | **Canvas 2D** | Controllo totale, leggero, nessuna dipendenza |
| Pochi elementi nitidi, icone, grafici scalabili | **SVG + CSS/SMIL** | Vettoriale, stilabile, accessibile |
| Pannelli, card, transizioni, hover | **CSS** (transform/opacity) | GPU-accelerato, zero JS |
| Scene 3D vere (modelli, luci, ombre, >500 oggetti) | **three.js (WebGL)** | Pipeline 3D completa |
| 3D "finto" di poche sfere/linee | **Canvas 2D + proiezione prospettica** | 40 righe, nessuna libreria |
| Effetti a pixel (distorsioni, bloom) | **WebGL shader / OffscreenCanvas** | Calcolo per pixel in GPU |

## 1. Token di design (definiscili PRIMA, come variabili CSS)
```css
:root{
  --bg:#030b14;  --bg2:#08213a;      /* fondo + centro luminoso */
  --blue:#2f8bff; --ice:#9fe3ff;     /* accento primario + highlight */
  --line:#12395a; --text:#cfe9ff; --dim:#6f93b3;
  --ok:#4fd1a5; --warn:#ffb454; --err:#ff7a7a;
  color-scheme: dark;
}
```
Regole: 4-6 colori con nome · un accento + un highlight · stati (ok/warn/err) usati solo per stati · font di sistema (`"Segoe UI Variable"`, `system-ui`) se l'app è offline · numeri con `font-variant-numeric: tabular-nums` · niente maiuscolo ovunque, niente etichette decorative.

## 2. Architettura che regge nel tempo
```
dati (Python/JS) ──► stato  ──► update(dt) ──► draw()
   SSE / WebSocket     {}        smoothing      canvas
```
- **Stato separato dal disegno**: `state` riceve i dati grezzi, `sm` (smoothed) li insegue con `v += (target - v) * min(1, dt*4)`. Mai saltare da un valore all'altro.
- **Loop con dt**: `requestAnimationFrame`, `dt = min(0.05, (now-last)/1000)`. Ogni velocità è `unità/secondo * dt`, mai per-frame.
- **Protocollo a eventi JSON** (`{type:'stats'|'plugins'|'speak'|'chat', ...}`): aggiungere una funzione = aggiungere un `case`.
- **Modalità demo** se la connessione manca: l'HUD resta sempre visibile e testabile.
- Server → client: **SSE** (`EventSource`, riconnessione automatica, solo stdlib Python). Bidirezionale pesante/binario: WebSocket.

## 3. Canvas 2D: ricette

**Setup nitido su schermi HiDPI**
```js
const dpr=Math.min(devicePixelRatio||1,2);
cv.width=w*dpr; cv.height=h*dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
new ResizeObserver(resize).observe(cv.parentElement);
```
**Scala responsiva unica**: `R=min(W,H)*.46; S=R/414` e moltiplica ogni misura per `S`.

**Anello rotante orario con carico**
```js
ang += speed*dt;                       // in canvas, angolo crescente = senso orario
ctx.arc(cx,cy,r, ang, ang+load*TAU);   // arco di carico che ruota con l'anello
// tacche: n segmenti radiali a ang + k*TAU/n (più lunghe ogni 6)
```
**Filo curvo + impulso viaggiante**: `quadraticCurveTo(mx,my,sx,sy)` con `mx,my` = punto medio spostato perpendicolarmente di `sin(t)*k`; l'impulso è il punto della Bézier a `u=(t*vel)%1` → `(1-u)²P0 + 2(1-u)u C + u²P2`.

**Sfere luminose economiche (sprite)**: disegna UNA volta una sfera con gradiente radiale + alone su un canvas offscreen e poi usa `drawImage` scalato per ogni atomo. Mai `createRadialGradient` per atomo per frame.

**Alone/bagliore**: gradiente radiale semitrasparente sotto l'elemento. Evita `shadowBlur` nei loop caldi (costoso).

## 4. 3D senza librerie (proiezione prospettica)
```js
function rot(p,ay,ax){ // ruota su Y poi su X
  const cy=Math.cos(ay),sy=Math.sin(ay), x=p[0]*cy+p[2]*sy, z=-p[0]*sy+p[2]*cy;
  const cx=Math.cos(ax),sx=Math.sin(ax); return [x,p[1]*cx-z*sx,p[1]*sx+z*cx];
}
const s=F/(F+z);  X=cx+x*s;  Y=cy+y*s;   // F≈500-600; s = scala prospettica
```
- **Ordina per profondità** (z decrescente, lontano prima) e fai sfumare i legami lontani.
- **Molecola** = atomi su sfera con spirale aurea (`th=i*2.399963`) + legami ai 2 vicini più prossimi.
- **Separazione 3D "quando parla"**: ogni gruppo ha una direzione `d`; posizione = `p + d*E*sep` con `E` che insegue `0.45+0.55*ampiezza` mentre parla e `0` a riposo; piccolo `wobble` sinusoidale proporzionale a `E`. Tieni `sep` basso (≈ la metà del raggio del gruppo) per un effetto "respiro", non un'esplosione.
- Ampiezza vera: se hai il livello audio, mandalo come `level` 0..1 e usalo al posto della sinusoide simulata.

## 5. three.js (quando 2D non basta)
- `WebGLRenderer({antialias:true,alpha:true})`, `setPixelRatio(min(dpr,2))`, un solo `requestAnimationFrame`.
- Molti atomi uguali → **`InstancedMesh`** (1 draw call). Linee → `LineSegments` con un unico buffer aggiornato.
- Glow: `UnrealBloomPass` (EffectComposer) o sprite additivi (`blending: AdditiveBlending, depthWrite:false`).
- Libera sempre: `geometry.dispose()`, `material.dispose()`, `renderer.dispose()`.

## 6. SVG e CSS
- SVG: `stroke-dasharray` + `stroke-dashoffset` animato = linee che si disegnano/scorrono; `<animateTransform type="rotate">` per anelli semplici.
- CSS 3D: `perspective` sul contenitore, `transform-style: preserve-3d`, `transform: rotateY() translateZ()`.
- Anima **solo** `transform` e `opacity`. Mai `width/height/top/left` in animazione.
- `will-change` solo su elementi che animano davvero, e rimuovilo dopo.

## 7. Pattern HUD utili
| Pattern | Come |
|---|---|
| Anelli telemetria | un anello per metrica (GPU, CPU, RAM, disco, rete), arco = carico, satellite collegato al centro da un filo |
| Plugin/moduli | nodi su un anello esterno; opacità ridotta se disattivati; click = attiva/disattiva |
| Stato assistente | ascolto = quiete; parla = separazione/pulsazione; pensa = rotazione più veloce; errore = tinta `--err` |
| Radar/sweep | `conic-gradient` ruotato oppure linea + scia con alpha decrescente |
| Scanline/glitch | usali al massimo in un momento (avvio/errore), mai in permanenza |
| Typewriter chat | aggiungi caratteri con `setInterval`, mai `innerHTML` con testo esterno |

## 8. Chat nella UI
- Messaggi con `textContent` (mai `innerHTML`): il testo può venire dal modello o dal web.
- `aria-live="polite"` sul log, auto-scroll, limite massimo di messaggi (es. 200).
- Invio con Enter, focus visibile, input non bloccato durante la risposta.
- Bolle: utente a destra con bordo accento, assistente a sinistra neutra, sistema centrato e piccolo.

## 9. Performance
- Budget: 60 fps con < 4 ms di disegno. Misura con `performance.now()` attorno a `draw()`.
- Precalcola (sprite, geometrie, gradienti statici). Alloca fuori dal loop (niente `map/filter` su array enormi a ogni frame).
- Aggiorna il DOM a bassa frequenza (legenda ogni 300 ms), il canvas a ogni frame.
- Tab nascosta: `requestAnimationFrame` si ferma da solo; non usare `setInterval` per animare.
- Se i frame calano: riduci DPR a 1, dimezza tacche/particelle, spegni alone.

## 10. Accessibilità e qualità minima (sempre)
- `prefers-reduced-motion`: rallenta/ferma rotazioni e separazioni.
- Contrasto testo ≥ 4.5:1; le informazioni non devono dipendere solo dal colore (aggiungi valore numerico).
- `aria-label` sul canvas + legenda testuale degli stessi dati.
- Focus visibile su input/pulsanti; responsive fino a 360 px (chat sotto lo stage).

## 11. Sicurezza del ponte locale
- Server solo su `127.0.0.1`; controlla l'header `Host` (anti DNS-rebinding).
- Le POST richiedono un header custom (`X-HUD: 1`): blocca richieste cross-site senza dover gestire CORS.
- Limita dimensione del body e valida tipi; mai eseguire testo ricevuto come comando di sistema senza passare dal normale controllo dei tool di Jarvis.

## 12. Checklist di consegna
- [ ] Un solo elemento memorabile, il resto sobrio
- [ ] Nessun errore in console; testato in modalità demo e collegato
- [ ] Velocità basate su `dt`; valori smussati
- [ ] HiDPI, resize, mobile ok
- [ ] Reduced motion rispettato
- [ ] Nessun `innerHTML` con dati esterni
- [ ] Screenshot di controllo a riposo e nello stato "parla"

## 13. Snippet da riusare
```js
// loop standard
let last=performance.now(), t=0;
(function frame(now){ const dt=Math.min(.05,(now-last)/1000); last=now; t+=dt;
  update(dt); draw(); requestAnimationFrame(frame); })(last);

// easing esponenziale indipendente dal frame-rate
const approach=(v,target,speed,dt)=>v+(target-v)*Math.min(1,dt*speed);

// bézier quadratica
const bez=(u,a,c,b)=>(1-u)*(1-u)*a+2*(1-u)*u*c+u*u*b;
```
