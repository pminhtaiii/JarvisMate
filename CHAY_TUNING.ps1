param(
    [Parameter(Mandatory=$true)][ValidateSet('status','verify-resources','prepare','token-audit','seal-selection-policy','gpu-preflight','preflight','probe','latency-pilot','train','export','verify-export','evaluate','build-asr-views','compare','deployment-check')][string]$Phase,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$PhaseArguments
)
$ErrorActionPreference = 'Stop'
$llmProjectRoot = $PSScriptRoot
$llmPython = Join-Path $llmProjectRoot '.venv-llm/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $llmPython)) { throw 'Create the separate .venv-llm first; see fine-tune-llm/RUNBOOK.md.' }
$env:PYTHONPATH = Join-Path $llmProjectRoot 'python/src'
$env:PYTHONIOENCODING = 'utf-8'
Push-Location -LiteralPath $llmProjectRoot
try { & $llmPython -m lifemate.llm_training $Phase @PhaseArguments; $llmExitCode = $LASTEXITCODE }
finally { Pop-Location }
exit $llmExitCode
