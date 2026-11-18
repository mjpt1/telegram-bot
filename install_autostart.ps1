# Start the userbot automatically when you log in to Windows.
# Usage:   powershell -ExecutionPolicy Bypass -File install_autostart.ps1
# Remove:  powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
param([switch]$Remove)

$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "Telegram Userbot.lnk"

if ($Remove) {
    if (Test-Path $link) { Remove-Item $link; Write-Host "Autostart removed." } else { Write-Host "Autostart was not installed." }
    exit
}

$bat = Join-Path $PSScriptRoot "run_forever.bat"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = $bat
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle = 7  # minimized
$s.Save()
Write-Host "Autostart installed: $link"
Write-Host "Note: the proxy (xray) must also start with Windows, or the bot cannot connect."
