$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pythonPath = (Get-Command python).Source
$azaharPath = "$env:LOCALAPPDATA/Programs/Azahar/azahar.exe"
if (-not (Test-Path -LiteralPath $azaharPath)) { $azaharPath = 'D:/Proyectos/3ds/PokeRogue3DS/tools/emulator/azahar.exe' }
if (-not (Test-Path -LiteralPath $azaharPath)) { throw "No se encuentra Azahar: $azaharPath" }
$endpoint = Get-NetUDPEndpoint -LocalPort 5000 -ErrorAction SilentlyContinue
if (-not $endpoint) {
    Start-Process -FilePath $pythonPath -ArgumentList 'server.py --url https://pokerogue.net --channel msedge --visible --bind 127.0.0.1 --fps 30' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput "$taskRoot/server.log" -RedirectStandardError "$taskRoot/server-error.log"
}
Start-Process -FilePath $azaharPath -ArgumentList "$taskRoot/client/rogue_stream.3dsx"
