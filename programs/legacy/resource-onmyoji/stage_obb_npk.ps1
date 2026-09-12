$ErrorActionPreference = "Stop"

$base = Split-Path -Parent $PSScriptRoot
$obbRoot = Join-Path $base "obb"
$stage = Join-Path $base "staging\obb_npk"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem

$archives = @(
  @{ Path = (Join-Path $obbRoot "main.251120.com.netease.onmyoji.na.obb"); Names = @("tex1.npk", "tex2.npk", "tex3.npk", "tex4.npk", "tex5.npk", "res1.npk", "res2.npk") },
  @{ Path = (Join-Path $obbRoot "patch.251120.com.netease.onmyoji.na.obb"); Names = @("tex6.npk", "tex7.npk", "tex8.npk", "tex9.npk", "tex10.npk", "tex11.npk", "script.npk") }
)

foreach ($archiveInfo in $archives) {
  if (-not (Test-Path -LiteralPath $archiveInfo.Path)) { throw "Missing OBB: $($archiveInfo.Path)" }
  $archive = [IO.Compression.ZipFile]::OpenRead($archiveInfo.Path)
  try {
    foreach ($name in $archiveInfo.Names) {
      $entry = $archive.GetEntry($name)
      if ($null -eq $entry) { throw "Missing OBB entry: $name" }
      $destination = Join-Path $stage $name
      if ((Test-Path -LiteralPath $destination) -and ((Get-Item -LiteralPath $destination).Length -eq $entry.Length)) {
        continue
      }
      [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
    }
  } finally {
    $archive.Dispose()
  }
}

Get-ChildItem -LiteralPath $stage -Filter *.npk -File | Select-Object Name, Length
