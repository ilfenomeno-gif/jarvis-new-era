# 04 — Reset camera (`camera_reset`)

Data prova: 2026-10-04.

## Fase 0 — Preflight

- Jarvis e GEV erano avviati; la UI aveva segnalato `GEV: ready`.
- Branch di entrambi i repository: `feat/gev-integration`.
- Codice condiviso committato in Jarvis `46ded87`; nessuna modifica di codice
  per questo ciclo.
- Baseline: `py_compile ui.py plugins/gev_plugin.py` superato;
  `pytest tests/test_gev_mcp_client.py -q` → 25 passed.

## Fase 1 — Analisi e diagnosi

- Il plugin espone `reset_camera`, mappato a `camera_reset`.
- La UI sostituisce lo stato camera con la vista globale, senza confonderlo
  con il reset completo `reset`.
- Il comando generico “Jarvis, torna alla vista globale” ha selezionato
  `reset`, non `reset_camera`. Per isolare il controllo camera è stata usata
  una frase esplicita.

## Fase 2 — Piano

Portare la vista fuori dallo stato globale con i controlli camera precedenti,
inviare “Jarvis, usa il plugin GEV per resettare solo la camera”, verificare
`camera_reset` nel log e conservare la schermata dopo l'azione.

## Fase 3 — Fattibilità

| Controllo | Esito | Evidenza |
|---|---|---|
| Azione distinta dal reset completo | Sì nel codice | `reset_camera` mappa a `camera_reset`; `reset` è un'altra azione |
| Stato camera ripristinabile | Sì | Implementazione nel bridge UI |
| GEV pronto | Sì | Log `GEV: ready` |
| Prova automatica disponibile | Sì | Suite mirata, 25 passed |
| Prova live conservabile | Sì | Screenshot acquisito dopo inclinazione/rotazione |

**Verdetto:** fattibile; l'ambiguità della frase generica resta un follow-up di
routing, non un motivo per attribuire `camera_reset` al comando sbagliato.

## Fase 4 — Implementazione

Nessuna modifica separata. Il bridge condiviso è nel commit Jarvis
`46ded87 feat(gev): add historical and camera dispatch`.

## Fase 5 — Verifica tecnica

`py_compile ui.py plugins/gev_plugin.py` superato;
`pytest tests/test_gev_mcp_client.py -q` → 25 passed. I test verificano
l'inoltro; la prova live documenta separatamente il routing.

## Fase 6 — Convalida reale

- Comando camera esplicito: “Jarvis, usa il plugin GEV per resettare solo la
  camera”.
- Log UI: `GEV: invio azione 'reset_camera'
  (bridge=camera_reset, params={})`.
- Risposta: “Torno alla vista globale, Signore.”
- Screenshot conservato: [04-camera-reset-visivo.png](./04-camera-reset-visivo.png).
- Controllo negativo di routing: “Jarvis, torna alla vista globale” ha
  selezionato `reset` (“Resetto la vista di God's Eye View, Signore.”).
- Microfono: non provato; la prova è stata testuale.
- Revisione personale dello screenshot richiesta dal proprietario: pendente.

## Fase 7 — Inventario

L'inventario distingue ora il comando camera esplicito dal reset completo e
registra entrambi i risultati osservati (`docs/MECCANICHE_GEV_JARVIS.md`,
commit Jarvis `0572d74`).

## Fase 8 — Recap

`camera_reset` è stato dispatchato con il comando esplicito dopo gli altri
controlli camera. Il comando generico non è equivalente e resta una voce di
follow-up. Screenshot conservato; revisione personale pendente. Nessun commit
separato: il blocco condiviso è `46ded87`.
