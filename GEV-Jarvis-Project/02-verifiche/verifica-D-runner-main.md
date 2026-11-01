# Verifica D — Runner e main

## Obiettivo

Ricostruire creazione del task Jarvis e percorso di shutdown del runner.

## Cosa è stato verificato

`main()` costruisce un runner/thread, conserva riferimenti a task/loop e alla chiusura segnala shutdown, cancella il task in modo thread-safe e attende il thread. `JarvisLive.run()` controlla l'evento shutdown e ha un `finally` che arresta il lifecycle plugin. Riferimenti: `main.py:2065-2069`, `:2103-2107`, `:2268-2310`; commit `29c198d`.

## Come

- Lettura selettiva `main.py` attorno a `JarvisLive.__init__`, `run()` e `main()`.
- `git show 29c198de07ecbabbce95674d6028e7be5f3cc5d9 --stat`.

## Risultato e stato

**Verificato nel codice**: esiste il percorso implementativo. Non è dimostrato che tutte le modalità di chiusura UI lo attivino correttamente; non sono stati avviati Jarvis né il suo runner.

> Da verificare: prova manuale con chiusura finestra e Ctrl+C, incluse eccezioni e task non cancellabile.

