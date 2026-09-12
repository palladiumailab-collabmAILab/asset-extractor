param(
    [Parameter(Mandatory = $true)]
    [string]$ApkPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) {
    throw "APK not found: $ApkPath"
}

$apkFullPath = (Resolve-Path -LiteralPath $ApkPath).Path
$outFullPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$packageRoot = Join-Path $outFullPath 'apk'
$assetsRoot = Join-Path $outFullPath 'assets'
$reportsRoot = Join-Path $outFullPath 'reports'

New-Item -ItemType Directory -Force -Path $packageRoot, $assetsRoot, $reportsRoot | Out-Null

Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipListing = [System.IO.Compression.ZipFile]::OpenRead($apkFullPath)
try {
    $entries = @($zipListing.Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_.FullName) })
    $entryRows = foreach ($entry in $entries) {
        $normalized = $entry.FullName.Replace('\', '/')
        $extension = [System.IO.Path]::GetExtension($normalized).ToLowerInvariant()
        $topLevel = ($normalized -split '/')[0]
        [pscustomobject]@{
            Path = $normalized
            Size = [int64]$entry.Length
            CompressedSize = [int64]$entry.CompressedLength
            Extension = $extension
            TopLevel = $topLevel
            IsDirectory = $normalized.EndsWith('/')
        }
    }
}
finally {
    $zipListing.Dispose()
}

[System.IO.Compression.ZipFile]::ExtractToDirectory($apkFullPath, $packageRoot, $true)

$apkHash = (Get-FileHash -LiteralPath $apkFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifestPath = Join-Path $packageRoot 'AndroidManifest.xml'

$assetFiles = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File | Where-Object {
    $_.FullName.Substring($packageRoot.Length).TrimStart('\', '/') -like 'assets\*' -or
    $_.FullName.Substring($packageRoot.Length).TrimStart('\', '/') -like 'assets/*'
})
foreach ($asset in $assetFiles) {
    $relative = $asset.FullName.Substring((Join-Path $packageRoot 'assets').Length).TrimStart('\', '/')
    $target = Join-Path $assetsRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $asset.FullName -Destination $target -Force
}

$fileRows = foreach ($file in Get-ChildItem -LiteralPath $packageRoot -Recurse -File) {
    $relative = $file.FullName.Substring($packageRoot.Length).TrimStart('\', '/').Replace('\', '/')
    $category = if ($relative -like 'assets/*') { 'assets' }
                elseif ($relative -like 'res/*') { 'res' }
                elseif ($relative -like 'lib/*') { 'native-libs' }
                elseif ($relative -like 'META-INF/*') { 'signature-metadata' }
                elseif ($relative -like 'classes*.dex') { 'dex' }
                elseif ($relative -eq 'AndroidManifest.xml') { 'manifest' }
                else { 'other' }
    [pscustomobject]@{
        Path = $relative
        Category = $category
        Extension = [System.IO.Path]::GetExtension($relative).ToLowerInvariant()
        Size = [int64]$file.Length
        SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$fileRows | Sort-Object Path | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $reportsRoot 'file-inventory.csv')
$entryRows | Sort-Object Path | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $reportsRoot 'zip-entry-inventory.csv')
$fileRows | Group-Object Category | Sort-Object Name | Select-Object Name, Count, @{Name='Bytes'; Expression={ ($_.Group | Measure-Object Size -Sum).Sum }} | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $reportsRoot 'category-summary.csv')
$fileRows | Group-Object Extension | Sort-Object Name | Select-Object Name, Count, @{Name='Bytes'; Expression={ ($_.Group | Measure-Object Size -Sum).Sum }} | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $reportsRoot 'extension-summary.csv')

$report = [ordered]@{
    apk = $apkFullPath
    apkSha256 = $apkHash
    apkBytes = (Get-Item -LiteralPath $apkFullPath).Length
    extractedDirectory = $packageRoot
    assetsDirectory = $assetsRoot
    entryCount = $entries.Count
    extractedFileCount = $fileRows.Count
    assetFileCount = $assetFiles.Count
    assetBytes = [int64](($fileRows | Where-Object Category -eq 'assets' | Measure-Object Size -Sum).Sum)
    nativeLibraryCount = ($fileRows | Where-Object Category -eq 'native-libs').Count
    dexFileCount = ($fileRows | Where-Object Category -eq 'dex').Count
    reports = @(
        'reports/file-inventory.csv',
        'reports/zip-entry-inventory.csv',
        'reports/category-summary.csv',
        'reports/extension-summary.csv'
    )
}
$report | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $reportsRoot 'analysis.json')

Write-Output "APK SHA256: $apkHash"
Write-Output "Extracted files: $($fileRows.Count)"
Write-Output "Asset files: $($assetFiles.Count)"
Write-Output "Asset bytes: $($report.assetBytes)"
Write-Output "Output: $outFullPath"
