# Prompt chiave e cronologia delle richieste

## Limite delle fonti

Nel materiale Git letto non è presente un log storico dei prompt dell'agente. La conversazione disponibile documenta la richiesta archivistica attuale, ma non conserva il testo o le date di prompt precedenti. Le righe qui sotto sono quindi riepiloghi dedotti dai commit, non citazioni né prova dell'ordine dei prompt.

| Ordine deducibile | Obiettivo ricostruibile | Passo | Risultato verificabile | Fonte |
|---|---|---|---|---|
| 1 | Analizzare l'integrazione e la UI/requirements | Analisi / 1 | Pin PyQt6 e QtWebEngine nel commit | `949e2ed114f83bf067ad9f1afbfde42a788e8835` |
| 2 | Aggiungere lifecycle start/stop nei plugin | 2 | Hook opzionali nel loader | `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8` |
| 3 | Coordinare shutdown in `main.py` | 3 | Eventi e cancellazione thread-safe | `29c198de07ecbabbce95674d6028e7be5f3cc5d9` |
| 4 | Implementare start/stop GEV con Node portatile | 4a | Plugin lifecycle, Job Object e health check | `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e` |
| 5 | Implementare dispatcher GEV | 4b | Diff locale non committato trovato; bridge non verificato | `git diff -- plugins/gev_plugin.py`, nessun hash |

> Da verificare: prompt iniziale integrale e i prompt specifici Passo 1, 2, 3, 4a e 4b. L'associazione prompt→commit è solo una ricostruzione cronologica; non sostituirla a una history agente verificabile.

