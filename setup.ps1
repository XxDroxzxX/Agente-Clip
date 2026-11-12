# ============================================================
# setup.ps1 - Instalador del Agente de Clips
# Ejecutar una vez (o para reparar):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup.ps1
# ============================================================
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$errors = @()

function Step($n, $msg) { Write-Host "`n[$n/5] $msg" -ForegroundColor Cyan }
function Ok($msg)       { Write-Host "    OK: $msg" -ForegroundColor Green }
function Fail($msg)     { Write-Host "    ERROR: $msg" -ForegroundColor Red }

Step 1 "Verificando Python..."
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Fail "Python no esta en el PATH. Instala Python 3.11+ desde https://python.org (marca 'Add python.exe to PATH')."
    exit 1
}
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Ok "Python $ver"

Step 2 "Entorno virtual..."
$venvPy = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & python -m venv venv
    if ($LASTEXITCODE -ne 0) { Fail "No se pudo crear el venv."; exit 1 }
    Ok "venv creado"
} else { Ok "venv existente" }

Step 3 "Instalando dependencias (incluye ffmpeg)..."
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPy -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "pip install fallo. Revisa tu conexion."; $errors += "dependencias" } else { Ok "Dependencias instaladas" }

Step 4 "Animaciones (Remotion)..."
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "    AVISO: Node.js no esta instalado; las animaciones quedan desactivadas." -ForegroundColor Yellow
    Write-Host "    Instala Node.js LTS desde https://nodejs.org y vuelve a abrir AgenteDeClips.exe." -ForegroundColor Yellow
} else {
    Push-Location (Join-Path $ProjectRoot "motion")
    & npm ci --no-audit --no-fund --loglevel=error
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    AVISO: no se pudo instalar Remotion (npm ci). Las animaciones quedan desactivadas." -ForegroundColor Yellow
    } else {
        & npx remotion browser ensure | Out-Null
        Ok "Remotion instalado (Node $(& node --version))"
    }
    Pop-Location
}

Step 5 "Carpetas..."
foreach ($d in @("data", "runs", "assets\music")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $d) | Out-Null
}
Ok "data/, runs/, assets/music/"

Write-Host ""
if ($errors.Count -eq 0) {
    # Marca para que AgenteDeClips.exe sepa que las dependencias estan al dia
    $lock = Join-Path $ProjectRoot "motion\package-lock.json"
    $mark = (Get-FileHash (Join-Path $ProjectRoot "requirements.txt") -Algorithm SHA256).Hash + "-" +
            $(if (Test-Path $lock) { (Get-FileHash $lock -Algorithm SHA256).Hash } else { "" })
    $mark | Set-Content -Encoding ascii (Join-Path $ProjectRoot "venv\.requirements.sha256")
    Write-Host "Instalacion completa." -ForegroundColor Green
    Write-Host "Abre la interfaz con AgenteDeClips.exe (o .\run_ui.ps1)" -ForegroundColor White
    Write-Host "Ahi configuras credenciales, conectas cuentas y lanzas runs." -ForegroundColor Gray
} else {
    Write-Host "Instalacion con errores: $($errors -join ', ')" -ForegroundColor Red
    exit 1
}
