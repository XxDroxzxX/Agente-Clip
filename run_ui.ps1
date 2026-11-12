# ============================================================
# run_ui.ps1 - Abre la interfaz del Agente de Clips
# http://localhost:8585  (solo accesible desde este equipo)
# ============================================================
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$venvPy = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "No existe el entorno virtual. Ejecuta primero .\setup.ps1" -ForegroundColor Red
    exit 1
}
$env:PYTHONUTF8 = "1"
& $venvPy -m app.server
