# ============================================================
# launcher\build.ps1 - Compila AgenteDeClips.exe en la raiz del proyecto.
# Usa el compilador de C# incluido en Windows (.NET Framework 4.x);
# no requiere instalar nada.
# ============================================================
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { Write-Host "No se encontro csc.exe (.NET Framework 4)." -ForegroundColor Red; exit 1 }

$out = Join-Path $root "AgenteDeClips.exe"
# Si el lanzador esta abierto, Windows no deja sobrescribirlo pero si moverlo.
if (Test-Path $out) {
    try { Remove-Item $out -Force -ErrorAction Stop }
    catch { Move-Item $out (Join-Path $env:TEMP ("AgenteDeClips.old.{0}.exe" -f (Get-Date -Format yyyyMMddHHmmss))) -Force }
}
& $csc /nologo /target:winexe /optimize+ /codepage:65001 `
    "/win32icon:$here\icon.ico" "/out:$out" `
    /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:Microsoft.CSharp.dll /r:System.Management.dll `
    "$here\AgenteDeClips.cs"
if ($LASTEXITCODE -ne 0) { Write-Host "Error de compilacion." -ForegroundColor Red; exit 1 }
Write-Host "OK: $out" -ForegroundColor Green
