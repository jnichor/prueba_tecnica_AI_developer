# Ayuda opcional para preparar Ollama desde Windows PowerShell 5.1 o superior.
# Python realiza la preparación y la descarga; este archivo solo inicia ese comando.
param([switch]$PrepararModelo)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
# Ejecutar desde la raíz permite encontrar el paquete scripts sin cambiar Python.
Push-Location -LiteralPath $projectRoot
try {
    & python -m scripts.run_casos --modo ollama --solo-preparar
    $prepareExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $prepareExitCode
