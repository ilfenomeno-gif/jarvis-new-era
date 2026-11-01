# Test avvio GEV

**Piano, non risultato.** Il plugin usa porta `4173`, timeout health `60s` e timeout install `600s` (`plugins/gev_plugin.py:19-25`, `:284-373`).

| Caso | Procedura | Criterio atteso | Stato |
|---|---|---|---|
| Primo avvio con install | Con `.node/node.exe` disponibile e senza `node_modules`, lanciare `start()` in ambiente isolato | npm install termina 0, Vite risponde HTTP 200 entro timeout, log “pronto” | Da eseguire |
| Avvio successivo | Ripetere con `node_modules` già presente | Salta install; health check completa; tempo registrato separatamente | Da eseguire |
| Health check fallito | Fermare Vite/non rispondere sulla porta | Timeout esplicito, process cleanup e log diagnostico | Da eseguire |
| Porta in conflitto | Avviare server di prova su 4173 prima di start | Plugin segnala conflitto e non termina il listener preesistente | Da eseguire |
| Runtime mancante | Rinominare/omettere `.node/node.exe` in ambiente temporaneo di test | `FileNotFoundError` esplicito | Da eseguire |

Riferimenti implementazione: `plugins/gev_plugin.py:155-174`, `:269-373`. Output di test effettivo: **> Da verificare**.

