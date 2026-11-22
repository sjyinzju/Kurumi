param(
    [Parameter(Mandatory = $true)][string]$PriorRelease,
    [Parameter(Mandatory = $true)][string]$FrozenBase,
    [Parameter(Mandatory = $true)][string]$BatchDirectory,
    [Parameter(Mandatory = $true)][string]$FinancialStage,
    [string]$DataRoot = 'E:\QuantData',
    [string]$Python = 'E:\quant\.venv\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repository
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$repository\src;$repository\scripts"
$numeric = Join-Path $DataRoot 'numeric'
$active = Get-Content -LiteralPath (Join-Path $numeric 'latest_cn.json') -Raw | ConvertFrom-Json
if ($active.path -cne $PriorRelease -or $active.dataset_version -cne $PriorRelease -or $PriorRelease -notmatch '^cn-[a-f0-9]{64}$') {
    throw 'The verified prior release is no longer the current CN source.'
}
$release = Join-Path $numeric $PriorRelease
$manifest = Join-Path $release 'manifest.json'
$published = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$suspension = Join-Path $release 'reference\official_suspensions.json'
if ((Get-FileHash -LiteralPath $suspension -Algorithm SHA256).Hash.ToLowerInvariant() -cne $published.source_snapshot.suspension_evidence_sha256) {
    throw 'The verified suspension source differs from the prior release.'
}
$workspace = Join-Path $numeric '.build-cn'
$marketStage = Join-Path $BatchDirectory 'market-stage'
$finance = Join-Path $FinancialStage 'financial_versions.jsonl'
$financeAudit = Join-Path $FinancialStage 'bse_financial_gap_stage.json'
$financeReceipt = Get-Content -LiteralPath $financeAudit -Raw | ConvertFrom-Json
if ($financeReceipt.release -cne $PriorRelease -or (Get-FileHash -LiteralPath $finance -Algorithm SHA256).Hash.ToLowerInvariant() -cne $financeReceipt.decisions.output_sha256) {
    throw 'The financial candidate is not the verified stage for this release.'
}
$fragments = @()
foreach ($stream in @('security_name_versions', 'stock_limit_evidence', 'split_coverage', 'split_events')) {
    $piece = Get-Item -LiteralPath (Join-Path $marketStage "$stream.jsonl")
    if ($piece.Length -gt 0) { $fragments += @('--append-to', "$stream.jsonl", $piece.FullName) }
}
$shares = Join-Path $BatchDirectory 'csmar_share_additions.jsonl'
if (Test-Path -LiteralPath $shares) { $fragments += @('--append-to', 'share_versions.jsonl', $shares) }
$audits = @($financeAudit,
    (Join-Path $BatchDirectory 'csmar_capture_audit.json'),
    (Join-Path $BatchDirectory 'csmar_capital_action_audit.json'),
    (Join-Path $BatchDirectory 'csmar_industry_audit.json'),
    (Join-Path $BatchDirectory 'csmar_fx_full_replay.json'),
    (Join-Path $BatchDirectory 'csmar_share_replay.json'),
    (Join-Path $BatchDirectory 'bse-originals-final\bse_financial_originals_audit.json'),
    (Join-Path $BatchDirectory 'bse_batch_financial_replay.json'),
    (Join-Path $marketStage 'tushare_market_gap_stage.json'),
    (Join-Path $marketStage 'tushare_csmar_units_audit.json'))

$frozen = & $Python scripts/stage_cn_pit_evidence.py --output-root (Join-Path $workspace 'sources\pit-releases') `
    --base-from $FrozenBase --base-manifest $manifest --merge-directory (Join-Path $BatchDirectory 'merged') `
    --replace-with $finance @fragments @audits
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $frozen -PathType Container)) { throw 'Source freeze failed.' }
$frozen | Set-Content -LiteralPath (Join-Path $BatchDirectory 'frozen_batch_path.txt') -Encoding utf8NoBOM
Write-Output $frozen

& $Python -u scripts/build_cn_numeric.py --data-root $DataRoot --pit-evidence $frozen `
    --calendar-prehistory (Join-Path $repository 'artifacts\cn-calendar\trade_cal') `
    --suspension-evidence $suspension --spill-dir (Join-Path $env:TEMP 'kurumi-cn-gap-batch-spill') --memory-limit-gib 8 `
    2>&1 | Tee-Object -FilePath (Join-Path $BatchDirectory 'publication.log')
exit $LASTEXITCODE
