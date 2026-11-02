param(
    [ValidateSet('lora','nf4')][string]$Method = 'lora',
    [switch]$Preview,
    [switch]$CheckInputs,
    [string]$AsrReviews,
    [switch]$PrepareASR,
    [switch]$AcceptProvisionalE4,
    [string]$ResumeAsrJob,
    [string]$OrchestrationConfig
)
$ErrorActionPreference = 'Stop'
$llmPython = Join-Path $PSScriptRoot '.venv-llm/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $llmPython)) { throw 'Missing .venv-llm. See fine-tune-llm/RUNBOOK.md.' }
$llmPreviousPath = $env:PYTHONPATH
$llmPreviousEncoding = $env:PYTHONIOENCODING
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'python/src'
    $env:PYTHONIOENCODING = 'utf-8'
    if ($PrepareASR) {
        if ($CheckInputs -or $AsrReviews) { throw 'PrepareASR is separate from Qwen checks/training.' }
        $llmArguments = @('-m','lifemate.llm_training.asr_handoff')
        if (-not $Preview) {
            if (-not $AcceptProvisionalE4) { throw 'Use -AcceptProvisionalE4 only if you choose E4 for provisional LLM development.' }
            $llmArguments += @('--execute','--accept-provisional-e4','--operator',$env:USERNAME)
            if ($ResumeAsrJob) { $llmArguments += @('--resume',$ResumeAsrJob) }
        }
    }
    else {
        if ($AcceptProvisionalE4 -or $ResumeAsrJob) { throw 'ASR preparation flags require -PrepareASR.' }
        $llmArguments = @('-m','lifemate.llm_training.once','--method',$Method)
        if ($OrchestrationConfig) { $llmArguments += @('--orchestration-config',$OrchestrationConfig) }
        if ($Preview) { $llmArguments += '--preview' }
        if ($CheckInputs) { $llmArguments += '--check-inputs' }
        if ($AsrReviews) { $llmArguments += @('--asr-reviews',$AsrReviews) }
    }
    & $llmPython @llmArguments
    $llmExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $llmPreviousPath
    $env:PYTHONIOENCODING = $llmPreviousEncoding
}
exit $llmExitCode
