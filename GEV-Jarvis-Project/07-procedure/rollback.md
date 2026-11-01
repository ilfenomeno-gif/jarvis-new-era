# Rollback al branch `main`

Procedura descrittiva, **non eseguita**. La repo Jarvis osservata è su `feat/gev-integration` con una modifica locale in `plugins/gev_plugin.py`; non cancellare branch o working tree prima di mettere al sicuro tale diff. Base `main`: `b6bb1eddf46dfa8b6d30090185235d8840e1460e`; integrazione: `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e`.

## Conservare e verificare modifiche

```powershell
$jarvis = 'C:\Users\PC\Downloads\Mark-LIV-main\Mark-LIV-main'
git -C $jarvis status --short --branch
git -C $jarvis diff
git -C $jarvis diff --binary > "$env:TEMP\jarvis-gev-local.patch"
```

Esaminare il patch e conservarlo altrove se deve essere mantenuto. Il comando non altera la repo, ma il file risultante si trova nella directory temporanea.

## Passare a main e rimuovere branch locale

Solo dopo aver salvato eventuali modifiche:

```powershell
git -C $jarvis switch main
git -C $jarvis status --short --branch
git -C $jarvis branch -D feat/gev-integration
```

`-D` elimina il riferimento locale anche in presenza di commit non uniti; usarlo solo dopo aver confermato il salvataggio. Per aggiornare dal remote:

```powershell
git -C $jarvis pull --ff-only
git -C $jarvis log -1 --oneline
git -C $jarvis status --short --branch
```

Prima verificare che remote/branch configurati siano quelli attesi. Non è stato eseguito pull. Per GEV, `.node/` è non tracciata: non rimuoverla implicitamente durante rollback Jarvis.

> Da verificare: politica per conservare/cancellare il checkout GEV e runtime locale.

