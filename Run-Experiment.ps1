param(
    [Parameter(Mandatory=$true)][string[]]$Conditions,
    [Parameter(Mandatory=$true)][int[]]$Seeds,
    [Parameter(Mandatory=$true)][ValidateSet('mock','openrouter')][string]$Backend,
    [Parameter(Mandatory=$true)][double]$SafetyStock,
    [int]$InitialInventory = 0,
    [int]$EvaluationPeriods = 100,
    [ValidateSet('cost','bullwhip')][string]$Objective,
    [double]$BudgetUsd = 2,
    [int]$Workers = 1,
    [string]$Output = '',
    [switch]$Resume,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $bundledPython) { $scmPython = $bundledPython }
else { $scmPython = (Get-Command python -ErrorAction Stop).Source }
if ([string]::IsNullOrWhiteSpace($Output)) { $Output = Join-Path $PSScriptRoot ('results/run-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$culture = [System.Globalization.CultureInfo]::InvariantCulture
# Always use the final wrapper: this enables the Q_base explanation for CMT.
# SafetyStock is mandatory so a missing argument cannot silently select SS=0.
$runArgs = @((Join-Path $PSScriptRoot 'run_final.py'),'--conditions') + $Conditions + @('--seeds') + @($Seeds | ForEach-Object { [string]$_ }) + @('--backend',$Backend,'--safety-stock',$SafetyStock.ToString($culture),'--initial-inventory',[string]$InitialInventory,'--evaluation-periods',[string]$EvaluationPeriods,'--budget-usd',$BudgetUsd.ToString($culture),'--workers',[string]$Workers,'--output',$Output)
if ($Resume) { $runArgs += '--resume' }
if ($Objective) { $runArgs += @('--objective', $Objective) }
if ($DryRun) { $runArgs += '--dry-run' }
Push-Location -LiteralPath $PSScriptRoot
try { & $scmPython @runArgs; if ($LASTEXITCODE -ne 0) { throw 'SCM execution did not finish. Review the saved logs.' } }
finally { Pop-Location }
