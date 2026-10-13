$ErrorActionPreference = 'Stop'
$pythonWindow = (Get-Command pythonw).Source
Start-Process -FilePath $pythonWindow -ArgumentList ('"' + (Join-Path $PSScriptRoot 'server_gui.py') + '"') -WorkingDirectory $PSScriptRoot
