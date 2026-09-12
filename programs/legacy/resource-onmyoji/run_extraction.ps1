$ErrorActionPreference = "Stop"

# Reproducible, non-destructive extraction helper. It never writes to source APK,
# OBB, or NPK files. Run from any PowerShell working directory. Existing decoded
# files for the selected sources are overwritten when the extractor reruns.
$base = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $base "tools\NeoXtractor-source-v3.2"
$python = Join-Path $base "tools\neoxtractor-venv\Scripts\python.exe"
$extractor = Join-Path $base "tools\extract_nxpk.py"
$option = Join-Path $base "device_data\onmyoji_from_phone_download\onmyoji\Documents\OptionRes"
$extra = Join-Path $base "device_data\onmyoji_from_phone_download\onmyoji\Documents\ExtraRes\res.npk"
$obb = Join-Path $base "staging\obb_npk"

& (Join-Path $PSScriptRoot "stage_obb_npk.ps1") | Out-Host
if (-not $?) { throw "OBB staging failed" }

function Invoke-Extraction([string[]] $inputs, [string] $output) {
  & $python $extractor @inputs --output $output
  if ($LASTEXITCODE -ne 0) { throw "Extraction failed for $output with exit code $LASTEXITCODE" }
}

$modelInputs = @(
  "model1.npk", "qmodel.npk", "qmodel_2505.npk", "model2_2505.npk",
  "yinyangliao.npk", "yinyangliao_2505.npk", "zhaohuanwu.npk",
  "zhaohuanwu_2505.npk"
) | ForEach-Object { Join-Path $option $_ }
Invoke-Extraction $modelInputs (Join-Path $base "extracted\option_models")

$obbInputs = @(
  "tex1.npk", "tex2.npk", "tex3.npk", "tex4.npk", "tex5.npk", "tex6.npk",
  "tex7.npk", "tex8.npk", "tex9.npk", "tex10.npk", "tex11.npk", "res1.npk",
  "res2.npk"
) | ForEach-Object { Join-Path $obb $_ }
Invoke-Extraction $obbInputs (Join-Path $base "extracted\obb_assets")

Invoke-Extraction @($extra) (Join-Path $base "extracted\extrares_assets")

# Keep scene/material/image-map references in a separate output.  This pass is
# intentionally additive: it does not replace the broader ExtraRes decode.
& $python $extractor $extra --output (Join-Path $base "extracted\extrares_stage_refs") --stage
if ($LASTEXITCODE -ne 0) { throw "Stage reference extraction failed" }
