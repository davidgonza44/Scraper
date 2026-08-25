# Daily Windows start for this repository.
# Selects Node 24 via fnm for this PowerShell session only.
# Does not replace, uninstall, or change the system-global Node (for example Node 25).
# Does not delete .web, does not kill node.exe, and does not reinstall dependencies.

#Requires -Version 5.1

$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

function Write-DevInfo {
    param([string]$Message)
    Write-Host $Message
}

function Write-DevError {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Get-RequiredNodePin {
    foreach ($Name in @('.node-version', '.nvmrc')) {
        $Path = Join-Path $RepoRoot $Name
        if (Test-Path -LiteralPath $Path) {
            $Raw = (Get-Content -LiteralPath $Path -TotalCount 1 -ErrorAction Stop)
            if ($null -ne $Raw) {
                $Pin = [string]$Raw
                $Pin = $Pin.Trim()
                if ($Pin.Length -gt 0) {
                    return $Pin
                }
            }
        }
    }
    Write-DevError 'No se encontro .node-version ni .nvmrc con una version de Node.'
    exit 1
}

function Get-NodeMajorFromPin {
    param([string]$Pin)
    $Normalized = $Pin.Trim()
    if ($Normalized.StartsWith('v') -or $Normalized.StartsWith('V')) {
        $Normalized = $Normalized.Substring(1)
    }
    $Major = ($Normalized -split '\.')[0]
    if ($Major -notmatch '^\d+$') {
        Write-DevError "No se pudo interpretar la version de Node requerida: $Pin"
        exit 1
    }
    return $Major
}

function Test-FnmHasMajor {
    param([string]$Major)
    $ListOutput = & fnm list 2>&1 | Out-String
    $Pattern = '(?im)\bv' + [regex]::Escape($Major) + '\.\d+'
    return [regex]::IsMatch($ListOutput, $Pattern)
}

function Initialize-FnmSession {
    # Session-only env vars. Does not edit $PROFILE or the user PATH.
    fnm env --shell powershell | Out-String | Invoke-Expression
}

if (-not (Get-Command fnm -ErrorAction SilentlyContinue)) {
    Write-DevError 'fnm (Fast Node Manager) no esta instalado.'
    Write-Host ''
    Write-Host 'Este proyecto usa Node 24 LTS solo a traves de fnm.'
    Write-Host 'No se instala fnm automaticamente y no se modifica el Node global del sistema.'
    Write-Host ''
    Write-Host 'Ejecuta una sola vez:'
    Write-Host '  winget install Schniz.fnm'
    Write-Host ''
    Write-Host 'Cierra y vuelve a abrir PowerShell. Luego, en la raiz del repositorio:'
    Write-Host '  fnm install 24'
    Write-Host '  .\dev.ps1'
    exit 1
}

Initialize-FnmSession

$RequiredPin = Get-RequiredNodePin
$RequiredMajor = Get-NodeMajorFromPin -Pin $RequiredPin

if (-not (Test-FnmHasMajor -Major $RequiredMajor)) {
    Write-Host "Node $RequiredMajor no esta instalado en fnm. Se instalara ahora en el almacen de fnm."
    Write-Host 'Esto no desinstala ni reemplaza el Node global del sistema (por ejemplo Node 25).'
    Write-Host "Comando: fnm install $RequiredMajor"
    & fnm install $RequiredMajor
    if ($LASTEXITCODE -ne 0) {
        Write-DevError "fnm install $RequiredMajor fallo."
        Write-Host "Instala Node $RequiredMajor solo con fnm, sin tocar el Node global:"
        Write-Host "  fnm install $RequiredMajor"
        exit 1
    }
}

& fnm use $RequiredMajor
if ($LASTEXITCODE -ne 0) {
    Write-DevError "No se pudo seleccionar Node $RequiredMajor con fnm para esta sesion."
    Write-Host "Prueba: fnm install $RequiredMajor"
    Write-Host 'fnm administra esa version; no reemplaza el Node global del sistema.'
    exit 1
}

Initialize-FnmSession

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-DevError 'node no esta disponible en esta sesion despues de fnm use.'
    exit 1
}

$NodeVersion = (& node -v 2>&1 | Out-String).Trim()
if ($NodeVersion -notmatch '^v(\d+)\.') {
    Write-DevError "No se pudo interpretar node -v: $NodeVersion"
    exit 1
}
$ActiveMajor = $Matches[1]
if ($ActiveMajor -ne $RequiredMajor) {
    Write-DevError "BERA requiere Node $RequiredMajor LTS en esta sesion. node -v devolvio $NodeVersion."
    Write-Host 'Abortando para no arrancar Reflex con una major incorrecta.'
    Write-Host 'El Node global del sistema no debe usarse aqui. Comprueba: fnm use 24'
    exit 1
}

Write-DevInfo "Node activo en esta sesion: $NodeVersion (fnm). El Node global no se modifica."

$PythonExe = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-DevError 'No se encontro .venv\Scripts\python.exe.'
    Write-Host 'Crea o configura el entorno virtual en la raiz del repositorio. Por ejemplo:'
    Write-Host '  uv venv --python 3.12 .venv'
    Write-Host '  uv pip install --python .venv\Scripts\python.exe -e ".[dev]"'
    Write-Host 'O:'
    Write-Host '  py -3.12 -m venv .venv'
    Write-Host '  .\.venv\Scripts\python.exe -m pip install -e ".[dev]"'
    exit 1
}

$env:PYTHONPATH = 'src'
$env:REFLEX_USE_NPM = '1'

Write-DevInfo 'PYTHONPATH=src  REFLEX_USE_NPM=1'
Write-DevInfo 'Arranque normal: se reutiliza .web; no se mata node.exe; no se reinstalan dependencias.'
Write-Host 'Si el frontend esta corrupto, usa excepcionalmente: .\reset-frontend.ps1'
Write-Host ''

& $PythonExe -m reflex run
exit $LASTEXITCODE
