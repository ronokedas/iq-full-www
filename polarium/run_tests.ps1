# Executa testes de integridade da instalação
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "Executando Teste de Fumaça..." -ForegroundColor Cyan
python unified_ai_bot.py --package-smoke-test
