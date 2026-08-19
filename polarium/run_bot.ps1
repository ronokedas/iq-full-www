# Script de inicialização rápida do Robô Polarium Full
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $ScriptDir

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   Iniciando Polarium Full v1.0.0...     " -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

python unified_ai_bot.py
