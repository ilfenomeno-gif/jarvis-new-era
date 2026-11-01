# Passo 3 — Hook di main e shutdown

## Obiettivo

Avviare e arrestare il lifecycle plugin assieme al ciclo di vita di Jarvis.

## File toccati

- `main.py`

## Modifiche chiave e commit

Commit `29c198de07ecbabbce95674d6028e7be5f3cc5d9` — `feat(main): wire shutdown signal for plugin lifecycle`. `JarvisLive.__init__` crea due eventi e avvia `start_all` su un thread daemon (`main.py:931-941`); `run()` salva loop/task (`:2065-2069`) e usa l'evento di shutdown (`:2103-2107`); il `finally` protegge lo stop plugin (`:2268-2274`). `main()` cancella il task con `call_soon_threadsafe` e attende il runner (`:2276-2310`).

## Test e note

Output test: non eseguiti. L'esistenza del percorso statico non dimostra le condizioni reali di chiusura della finestra o Ctrl+C.

> Da verificare: integrazione runtime UI/loop, chiusura ripetuta e task bloccato.

