# Exceptional recovery for a corrupt Reflex frontend.
# Not called by dev.ps1. Daily start is: .\dev.ps1
# Stops only processes clearly tied to this repository's frontend.
# Never runs: taskkill /F /IM node.exe

#Requires -Version 5.1

$ErrorActionPreference = 'Stop'

$RepoRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
Set-Location -LiteralPath $RepoRoot

function Write-ResetError {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Get-Win32ProcessesByName {
    param([string]$ProcessName)
    try {
        return @(Get-CimInstance -ClassName Win32_Process -Filter "Name = '$ProcessName'" -ErrorAction Stop)
    } catch {
        try {
            return @(Get-WmiObject -Class Win32_Process -Filter "Name = '$ProcessName'" -ErrorAction Stop)
        } catch {
            return @()
        }
    }
}

function Test-CommandLineContainsPath {
    param(
        [string]$CommandLine,
        [string]$PathValue
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine) -or [string]::IsNullOrWhiteSpace($PathValue)) {
        return $false
    }
    $Variants = @(
        $PathValue
        $PathValue.Replace('\', '/')
        $PathValue.Replace('/', '\')
    ) | Select-Object -Unique
    $LeadingBoundary = '(?:^|[\s''"])'
    $TrailingBoundary = '(?=$|[\s''"]|[\\/])'
    foreach ($Variant in $Variants) {
        $Pattern = $LeadingBoundary + [System.Text.RegularExpressions.Regex]::Escape($Variant) + $TrailingBoundary
        if ([System.Text.RegularExpressions.Regex]::IsMatch(
            $CommandLine,
            $Pattern,
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )) {
            return $true
        }
    }
    return $false
}

function Stop-MatchingProcess {
    param(
        $Process,
        [string]$Reason
    )
    $PidValue = $Process.ProcessId
    Write-Host "Deteniendo PID $PidValue ($Reason)"
    try {
        Stop-Process -Id $PidValue -Force -ErrorAction Stop
    } catch {
        Write-Host "No se pudo detener PID $PidValue : $($_.Exception.Message)"
    }
}

$WebDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot '.web'))
$VenvPython = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot '.venv\Scripts\python.exe'))

Write-Host 'Recuperacion excepcional del frontend Reflex.'
Write-Host 'Este script no forma parte del arranque diario. No lo ejecuta .\dev.ps1.'
Write-Host 'No se mata todo node.exe del sistema (Cursor, VS Code y otras apps usan Node).'
Write-Host ''

$Stopped = 0
foreach ($Proc in (Get-Win32ProcessesByName -ProcessName 'node.exe')) {
    $CommandLine = $Proc.CommandLine
    if (Test-CommandLineContainsPath -CommandLine $CommandLine -PathValue $WebDir) {
        Stop-MatchingProcess -Process $Proc -Reason 'node con .web de este repositorio'
        $Stopped += 1
    }
}

foreach ($Name in @('python.exe', 'pythonw.exe')) {
    foreach ($Proc in (Get-Win32ProcessesByName -ProcessName $Name)) {
        $CommandLine = $Proc.CommandLine
        $FromThisVenv = Test-CommandLineContainsPath -CommandLine $CommandLine -PathValue $VenvPython
        $LooksLikeReflex = $false
        if (-not [string]::IsNullOrWhiteSpace($CommandLine)) {
            $LooksLikeReflex = $CommandLine.IndexOf('reflex', [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        $FromThisRepo = Test-CommandLineContainsPath -CommandLine $CommandLine -PathValue $RepoRoot
        if ($FromThisVenv -and $LooksLikeReflex) {
            Stop-MatchingProcess -Process $Proc -Reason 'Python de .venv ejecutando Reflex'
            $Stopped += 1
        } elseif ($FromThisRepo -and $LooksLikeReflex -and ($CommandLine -match '(?i)-m\s+reflex|\breflex\.exe\b|\breflex\s+run\b')) {
            Stop-MatchingProcess -Process $Proc -Reason 'Python/Reflex de este repositorio'
            $Stopped += 1
        }
    }
}

if ($Stopped -eq 0) {
    Write-Host 'No se encontraron procesos de frontend claramente ligados a este repositorio.'
    Write-Host 'Si .web esta bloqueado, cierra primero la sesion de .\dev.ps1 / reflex run de este proyecto.'
} else {
    Start-Sleep -Seconds 1
}

if (Test-Path -LiteralPath $WebDir) {
    try {
        Remove-Item -LiteralPath $WebDir -Recurse -Force -ErrorAction Stop
        Write-Host 'Eliminado: .web'
    } catch {
        Write-ResetError "No se pudo eliminar .web : $($_.Exception.Message)"
        Write-Host 'Cierra el Reflex de este proyecto e intenta de nuevo. No uses taskkill /IM node.exe.'
        exit 1
    }
} else {
    Write-Host '.web no existia.'
}

Write-Host ''
Write-Host 'El siguiente .\dev.ps1 sera mas lento porque Reflex reconstruira el frontend.'
Write-Host 'Arranque diario (sin borrar .web): .\dev.ps1'
