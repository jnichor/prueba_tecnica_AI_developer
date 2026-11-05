# Prepara Ollama y el modelo antes de hacer preguntas, desde PowerShell 5.1 o superior.
# Por ejemplo, puedes usarlo hoy para dejar lista la IA y ejecutar los casos después.
# Python hace la preparación; este archivo solo inicia ese comando desde el lugar correcto.
param([switch]$PrepararModelo)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
# Entramos a la carpeta principal para que Python encuentre los comandos de scripts/.
Push-Location -LiteralPath $projectRoot
try {
    & python -m scripts.run_casos --modo ollama --solo-preparar
    $prepareExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $prepareExitCode
