$ErrorActionPreference = 'Stop'
$probePython = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $probePython) {
    python "$PSScriptRoot\diagnostics.py" --gui
} else {
    Start-Process -FilePath $probePython -ArgumentList @("`"$PSScriptRoot\diagnostics.py`"", '--gui') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}
