# ============================================================
# run_day.ps1 - Run diario sin interfaz (lo usa el Programador de tareas)
#
# Publica solo si "Publicar automaticamente" esta activo en la configuracion.
# El progreso queda en runs\<fecha>\ y se puede ver en la interfaz (Historial).
# ============================================================
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$venvPy = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "No existe el entorno virtual. Ejecuta primero .\setup.ps1" -ForegroundColor Red
    exit 1
}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $ProjectRoot "runs\$runId\console.log"
# El propio proceso escribe su registro (--console-log). Antes la salida pasaba por «| Tee-Object»: si esta
# ventana oculta se cerraba, el run moría sin dejar rastro (2026-11-18). Si el run anterior quedó interrumpido,
# el pipeline lo reanuda en vez de empezar otro.
& $venvPy -m agente.pipeline --run-id $runId --scheduled --console-log $log *> $null
exit $LASTEXITCODE
