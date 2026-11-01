# Scenari end-to-end

**Stato generale: da eseguire.** Le frasi vocali sono proposte di test, non trascrizioni storiche né prova di supporto end-to-end. Le azioni `open`, `track`, `layer`, `reset`, `annotate` compaiono nello schema del plugin nel diff locale; il commit lifecycle non le implementa (`plugins/gev_plugin.py` nel diff locale; commit `bbdcff8`). La UI bridge manca nel codice osservato (`ui.py:4156-4332`).

| # | Nome | Comando vocale proposto | Comportamento atteso da verificare | Verifica | Stato |
|---|---|---|---|---|---|
| 1 | Apertura globo | “Apri God's Eye View” | Jarvis avvia/mostra GEV e riferisce esito solo se raggiungibile | Log plugin, PID Node, HTTP 200 su `127.0.0.1:4173` | Da eseguire |
| 2 | Tracciamento volo | “Traccia il volo [codice]” | Dati validati e target aircraft passato a GEV | Messaggio bridge e target visibile | Da eseguire |
| 3 | Tracciamento nave | “Traccia la nave [MMSI]” | Tipo e ID validati e passati alla vista | Messaggio bridge e vista coerente | Da eseguire |
| 4 | Tracciamento satellite | “Traccia il satellite [NORAD ID]” | Tipo e ID validati e passati alla vista | Messaggio bridge e target visibile | Da eseguire |
| 5 | Abilitazione layer | “Attiva il layer voli” | Layer e booleano sono inviati al protocollo GEV compatibile | Stato layer prima/dopo | Da eseguire |
| 6 | Disabilitazione layer | “Disattiva il layer satelliti” | Layer si disattiva senza alterare altri layer | Stato layer prima/dopo | Da eseguire |
| 7 | Reset vista | “Ripristina il globo” | Camera/view torna al reset supportato dall'app | Vista iniziale verificata | Da eseguire |
| 8 | Annotazione | “Segna [testo] a latitudine [x], longitudine [y]” | Coordinate in range e testo valido raggiungono l'API GEV | Annotazione visibile dopo dispatch | Da eseguire |
| 9 | Parametri invalidi | “Traccia un volo” senza ID | Richiesta incompleta non viene inviata; risposta esplicita | Log, schema e assenza di messaggio dispatch | Da eseguire |
| 10 | GEV non disponibile | “Apri God's Eye View” con porta occupata/runtime mancante | Start fallisce esplicitamente senza terminare un processo estraneo | Log errore, PID preesistente intatto | Da eseguire |

## Metriche da raccogliere

| Metrica | Misura | Target |
|---|---|---|
| Copertura | Test passati / test pianificati | > Da verificare |
| p95 comando→conferma | Percentile 95 da utterance a conferma dell'azione | > Da verificare |
| Avvio primo GEV | Tempo start inclusa install se necessaria | > Da verificare; codice ha timeout install 600s e startup 60s (`plugins/gev_plugin.py:23-25`) |
| Avvio successivo GEV | Tempo senza install dipendenze | > Da verificare |
| Processi orfani | Numero di `node.exe`/connessioni 4173 dopo chiusura | 0 è obiettivo proposto, non risultato misurato |

