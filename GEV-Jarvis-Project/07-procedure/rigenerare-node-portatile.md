# Rigenerare Node portatile `.node/`

Questa procedura è documentazione per un'operazione futura: **non è stata eseguita** e non modifica ora le repo. Il plugin si aspetta `.node/node.exe` e `.node/node_modules/npm/bin/npm-cli.js` (`plugins/gev_plugin.py:155-174`). `package.json` dichiara Node `>=24.14.0 <25 || >=26 <27` (`package.json:17-19`).

## Versione

Il requisito operativo richiesto per questa integrazione è `>=24.14.0 <25`; la sorgente package ammette anche Node 26. **> Da verificare** quale minor/patch sia stata effettivamente testata per il runtime portatile. Non assumere che una versione sia stata installata solo perché `.node/` esiste.

## Comandi PowerShell (Windows x64, esempio Node 24.14.0)

Verificare prima architettura e disponibilità della release nell'archivio ufficiale. Eseguire i comandi dalla cartella di lavoro, senza sovrascrivere `.node` prima di aver validato lo staging.

```powershell
$gev = 'C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone'
$version = 'v24.14.0'
$archive = Join-Path $env:TEMP "node-$version-win-x64.zip"
$extract = Join-Path $env:TEMP "gev-node-$version"
$stage = Join-Path $gev ".node-stage"
$url = "https://nodejs.org/dist/$version/node-$version-win-x64.zip"

Invoke-WebRequest -Uri $url -OutFile $archive
Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
$dist = Join-Path $extract "node-$version-win-x64"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item (Join-Path $dist 'node.exe') $stage
Copy-Item (Join-Path $dist 'node_modules') $stage -Recurse

$node = Join-Path $stage 'node.exe'
& $node --version
Test-Path (Join-Path $stage 'node_modules\npm\bin\npm-cli.js')
```

Se entrambi i controlli sono corretti, sostituire con backup esplicito (non cancellare il backup finché il test non passa):

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$current = Join-Path $gev '.node'
if (Test-Path $current) {
    Rename-Item -LiteralPath $current -NewName ".node-backup-$stamp"
}
Rename-Item -LiteralPath $stage -NewName '.node'
& (Join-Path $gev '.node\node.exe') --version
Test-Path (Join-Path $gev '.node\node_modules\npm\bin\npm-cli.js')
```

## Verifica finale

La versione stampata deve soddisfare il range scelto; verificare anche entrambi i file attesi dal plugin. L'archivio ufficiale è `https://nodejs.org/dist/`. Comandi non eseguiti durante la raccolta.

> Da verificare: URL/versione concretamente scaricabile, checksum/signature richiesti dalla policy locale e compatibilità con le dipendenze GEV installate.

