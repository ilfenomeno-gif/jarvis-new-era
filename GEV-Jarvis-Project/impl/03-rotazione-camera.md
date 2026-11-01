# 03 — Rotazione camera (`camera_rotate`)

Data prova: 2026-10-04.

## Fase 0 — Preflight

- Jarvis e GEV erano avviati; GEV aveva già restituito `GEV: ready`.
- Branch di entrambi i repository: `feat/gev-integration`.
- Il bridge condiviso è nel commit Jarvis `46ded87`; non sono state apportate
  modifiche di codice in questo ciclo.
- Baseline Jarvis: compilazione mirata superata e
  `pytest tests/test_gev_mcp_client.py -q` → 25 passed.

## Fase 1 — Analisi e diagnosi

- Il plugin mappa `rotate` a `camera_rotate` e valida `heading_deg` nel range
  0..360.
- La UI applica il valore alla vista completa prima dell'invio `gev:view`.
- “Jarvis, ruota la vista di 90 gradi” ha selezionato
  `camera_rotate` con `heading_deg=90`.
- I test automatici coprono schema/inoltro, non l'orientamento effettivo
  percepito dalla persona.

## Fase 2 — Piano

Inviare il comando testuale dopo `GEV: ready`, verificare il payload nel log e
conservare uno screenshot della finestra integrata; non modificare il
dispatcher condiviso.

## Fase 3 — Fattibilità

| Controllo | Esito | Evidenza |
|---|---|---|
| Dispatcher/bridge esistono | Sì | Commit `46ded87`, plugin e UI |
| Valore valido | Sì | 90 è nel range 0..360 |
| GEV pronto | Sì | Log `GEV: ready` |
| Test disponibili | Sì | 25 test mirati passati |
| Evidenza live conservabile | Sì | Screenshot acquisito |

**Verdetto:** fattibile; nessuna implementazione isolata necessaria.

## Fase 4 — Implementazione

Nessuna modifica per questa singola azione. Il codice condiviso è stato
committato come `46ded87 feat(gev): add historical and camera dispatch`.

## Fase 5 — Verifica tecnica

`py_compile ui.py plugins/gev_plugin.py` superato;
`pytest tests/test_gev_mcp_client.py -q` → 25 passed. I test non misurano la
rotazione visibile.

## Fase 6 — Convalida reale

- Comando testuale: “Jarvis, ruota la vista di 90 gradi”.
- Log UI: `GEV: invio azione 'rotate' (bridge=camera_rotate,
  params={'heading_deg': 90})`.
- Risposta: “Ruoto la vista a 90°, Signore.”
- Screenshot conservato: [03-rotate-visivo.png](./03-rotate-visivo.png).
- Microfono: non provato.
- Revisione personale dello screenshot richiesta dal proprietario: pendente.

## Fase 7 — Inventario

L'inventario riporta il dispatch testuale e lo screenshot; la prova vocale non
è attestata. Vedere `docs/MECCANICHE_GEV_JARVIS.md` nel repository Jarvis,
committato in `0572d74`.

## Fase 8 — Recap

Il log dimostra `camera_rotate` con heading 90 e la schermata è stata
conservata. Non è stata eseguita una prova microfono; resta pendente la
revisione personale. La voce condivide il commit `46ded87` con le altre azioni
camera.
