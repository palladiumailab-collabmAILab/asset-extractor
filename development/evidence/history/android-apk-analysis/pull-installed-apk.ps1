param(
    [string]$AdbPath = 'adb',
    [string]$Serial = 'emulator-5554',
    [Parameter(Mandatory = $true)]
    [string]$PackageName,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$packageLines = @(& $AdbPath -s $Serial shell pm path $PackageName | Where-Object { $_ -match '^package:' })
if ($packageLines.Count -eq 0) {
    throw "No installed APK path found for package: $PackageName"
}

$index = 0
foreach ($line in $packageLines) {
    $devicePath = ($line -replace '^package:', '').Trim()
    $leaf = [System.IO.Path]::GetFileName($devicePath)
    if ([string]::IsNullOrWhiteSpace($leaf)) {
        $leaf = "split-$index.apk"
    }
    $prefix = if ($index -eq 0) { 'base' } else { "split-$index" }
    $localPath = Join-Path $OutputDirectory "$prefix-$leaf"
    & $AdbPath -s $Serial pull $devicePath $localPath
    if ($LASTEXITCODE -ne 0) {
        throw "adb pull failed for $devicePath"
    }
    [pscustomobject]@{
        Package = $PackageName
        Serial = $Serial
        DevicePath = $devicePath
        LocalPath = $localPath
        SHA256 = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Bytes = (Get-Item -LiteralPath $localPath).Length
    }
    $index++
}
