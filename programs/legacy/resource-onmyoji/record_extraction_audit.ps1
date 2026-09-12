$ErrorActionPreference = "Stop"

$base = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $base "device_data\onmyoji_from_phone_download\onmyoji"
$scriptPath = Join-Path $base "tools\extract_nxpk.py"
$scriptHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash
$commit = (& git -C (Join-Path $base "tools\NeoXtractor-source-v3.2") rev-parse HEAD).Trim()
$timestamp = (Get-Date).ToString("o")

$roots = @("extracted\option_models", "extracted\obb_assets", "extracted\extrares_assets", "extracted\extrares_stage_refs")
foreach ($relativeRoot in $roots) {
  $root = Join-Path $base $relativeRoot
  $manifests = Get-ChildItem -LiteralPath $root -Recurse -Filter extraction_manifest.json -File
  foreach ($manifestPath in $manifests) {
    $manifest = Get-Content -LiteralPath $manifestPath.FullName -Raw | ConvertFrom-Json
    $sourcePath = [string]$manifest.source
    $sourceHash = $null
    if (Test-Path -LiteralPath $sourcePath) {
      $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    }
    $audit = [ordered]@{
      recorded_at = $timestamp
      source_sha256 = $sourceHash
      extractor_script = $scriptPath
      extractor_script_sha256 = $scriptHash
      neoxtractor_source_commit = $commit
      decryption_key = $manifest.decryption_key
      extraction_mode = if ($manifest.entry_count -eq $manifest.header.file_count) { "full_or_all_entries" } else { "limited_or_partial" }
    }
    $manifest | Add-Member -NotePropertyName audit -NotePropertyValue ([PSCustomObject]$audit) -Force
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath.FullName -Encoding UTF8
  }
  $runManifest = Join-Path $root "run_manifest.json"
  if (Test-Path -LiteralPath $runManifest) {
    $runAudit = [ordered]@{
      recorded_at = $timestamp
      extractor_script = $scriptPath
      extractor_script_sha256 = $scriptHash
      neoxtractor_source_commit = $commit
      manifest_count = $manifests.Count
      source_root = $sourceRoot
    }
    $runAudit | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root "run_audit.json") -Encoding UTF8
  }
}
