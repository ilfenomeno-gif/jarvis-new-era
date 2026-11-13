param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Jarvis VII.lnk"

if ($Uninstall) {
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath
        Write-Output "Jarvis autostart removed."
    } else {
        Write-Output "Jarvis autostart was not installed."
    }
    exit 0
}

$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Jarvis virtual environment not found. Run .\.venv\Scripts\python.exe -m pip install -r requirements.txt first."
}

$mainScript = Join-Path $projectRoot "main.py"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$mainScript`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7
$iconPath = Join-Path $projectRoot "face.ico"
if (Test-Path -LiteralPath $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Description = "Start Jarvis VII minimized when you sign in."
$shortcut.Save()

Write-Output "Jarvis autostart installed for the current Windows user."
Write-Output "Shortcut: $shortcutPath"
Write-Output "To uninstall: powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Uninstall"
