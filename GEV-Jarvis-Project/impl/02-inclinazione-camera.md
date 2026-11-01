# 02 — Inclinazione camera (`camera_tilt`)

Data prova: 2026-10-04.

## Fase 0 — Preflight

- Jarvis e GEV sono stati avviati; il log UI aveva già restituito `GEV: ready`.
- Branch di entrambi i repository: `feat/gev-integration`.
- Blocco condiviso presente nel commit Jarvis `46ded87`; GEV storico in
  `2bc902b`. Non sono state apportate modifiche di codice per questo ciclo.
- Baseline Jarvis: `py_compile ui.py plugins/gev_plugin.py` superato;
  `pytest tests/test_gev_mcp_client.py -q` → 25 passed.

## Fase 1 — Analisi e diagnosi

- `plugins/gev_plugin.py` mappa `tilt` a `camera_tilt` e richiede
  `pitch_deg` compreso tra -90 e 0.
- `ui.py` aggiorna il campo pitch della vista camera completa prima di inviare
  `gev:view`.
- Nel test dal campo testuale, “Jarvis, inclina lo sguardo verso il basso” ha
  selezionato `camera_tilt` con `pitch_deg=-45`.
- I test Python verificano lo schema/inoltro, non l'aspetto finale del globo.

## Fase 2 — Piano

Usare la frase italiana riportata sopra dopo `GEV: ready`, verificare nel log
`camera_tilt` / `pitch_deg=-45`, acquisire lo stato della finestra integrata
e non cambiare il codice del blocco condiviso.

## Fase 3 — Fattibilità

| Controllo | Esito | Evidenza |
|---|---|---|
| Dispatcher e bridge presenti | Sì | Commit `46ded87`, `plugins/gev_plugin.py`, `ui.py` |
| Range compatibile | Sì | `pitch_deg=-45` è nel range -90..0 |
| Precondizione runtime | Sì | GEV aveva segnalato `ready` |
| Test automatici disponibili | Sì | Suite mirata 25 passed |
| Prova visiva conservabile | Sì | Screenshot catturato in questa sessione |

**Verdetto:** fattibile; implementazione condivisa già committata.

## Fase 4 — Implementazione

Nessuna modifica per singola meccanica. Il controllo è nel blocco comune
committato con `46ded87 feat(gev): add historical and camera dispatch`.

## Fase 5 — Verifica tecnica

Baseline/post-commit disponibile: `py_compile ui.py plugins/gev_plugin.py`
superato; `pytest tests/test_gev_mcp_client.py -q` → 25 passed. Questi test
provano schema e dispatch, non sostituiscono la prova live.

## Fase 6 — Convalida reale

- Comando testuale: “Jarvis, inclina lo sguardo verso il basso”.
- Log UI: `GEV: invio azione 'tilt' (bridge=camera_tilt,
  params={'pitch_deg': -45})`.
- Risposta: “Inclino la vista a -45°, Signore.”
- Screenshot conservato: [02-tilt-visivo.png](./02-tilt-visivo.png).
- Microfono: non provato.
- Revisione personale dello screenshot richiesta dal proprietario: pendente.

## Fase 7 — Inventario

L'inventario riporta l'esito testuale e lo screenshot; non attribuisce una prova
vocale. Vedere `docs/MECCANICHE_GEV_JARVIS.md` nel repository Jarvis,
committato in `0572d74`.

## Fase 8 — Recap

Il dispatch `camera_tilt` con pitch -45 è stato osservato nella UI e lo
schermo è stato conservato. La prova microfono non è stata eseguita; la
revisione personale dello screenshot resta da registrare. Nessun commit
separato per tilt: codice e test condividono il commit `46ded87`.
