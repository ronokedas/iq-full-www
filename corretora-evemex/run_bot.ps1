param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$BotArgs
)

$ErrorActionPreference = 'Stop'
$candidates = @()
$systemPython = Get-Command python -ErrorAction SilentlyContinue
if ($systemPython) {
    $candidates += $systemPython.Source
}
$candidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

$pythonPath = $null
foreach ($candidate in $candidates | Select-Object -Unique) {
    if (-not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    & $candidate -c "import sys" *> $null
    $candidateExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    if ($candidateExitCode -eq 0) {
        $pythonPath = $candidate
        break
    }
}

if (-not $pythonPath) {
    throw 'Python 3.11 ou superior não foi encontrado. Instale o Python e tente novamente.'
}

& $pythonPath (Join-Path $PSScriptRoot 'unified_ai_bot.py') @BotArgs
exit $LASTEXITCODE
