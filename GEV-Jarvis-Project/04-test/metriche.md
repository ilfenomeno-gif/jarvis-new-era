# Definizioni metriche e target

Le metriche sono definite per rendere ripetibili le prove; i valori misurati non sono disponibili.

| Metrica | Definizione operativa | Target | Evidenza disponibile |
|---|---|---|---|
| Copertura | Casi passati / casi previsti × 100, separando unit/integration/e2e | > Da verificare | Non esistono test lifecycle dedicati nel checkout osservato |
| p95 comando→conferma | 95° percentile del tempo monotonic fra ricezione comando vocale e conferma verificabile dell'azione | > Da verificare | Nessuna misura; il percorso end-to-end del dispatcher non è completo/verificato |
| Avvio GEV primo avvio | Tempo da richiesta `start()` fino a health HTTP 200, includendo `npm install` se `node_modules` manca | > Da verificare | Timeout install configurato 600s; startup 60s (`plugins/gev_plugin.py:23-25`) |
| Avvio GEV successivo | Tempo da `start()` fino a health HTTP 200 con dipendenze già presenti | > Da verificare | Nessun benchmark eseguito |
| Orfani | PID `node.exe` / listener 4173 appartenenti al test dopo lo stop | 0 proposto, da misurare | Implementati terminate/kill e Job Object (`plugins/gev_plugin.py:135-152`, `:183-265`) |

Non confondere timeout massimo, obiettivo e prestazione misurata. Il valore `60s` è un limite di startup implementato; non è una media né un p95.

