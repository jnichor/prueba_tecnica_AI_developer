# Wrapper opcional compatible con Windows PowerShell 5.1; Python hace el setup.
# No requiere PowerShell 7 ni instalación manual de Ollama.
param([switch]$PrepararModelo)
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run_casos.py') --modo ollama --solo-preparar
exit $LASTEXITCODE
