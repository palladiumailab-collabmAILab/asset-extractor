param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Get-CloudFileKey {
    param([UInt32]$Length, [byte]$HeaderByte)

    $seed = [UInt32]($Length + $HeaderByte)
    [byte[]]@(
        [byte]($Length % 253),
        [byte]($seed -band 0xff),
        [byte](($Length -shr 8) -band 0xff),
        [byte](($Length -shr 16) -band 0xff),
        0x6a, 0x6b, 0x2e, 0x7c,
        0x30, 0x36,
        [byte](($seed -bxor 0x33) -band 0xff),
        [byte](($seed -bor 0x2e) -band 0xff),
        0x6e, 0x65, 0x74, 0x5c
    )
}

function Get-DetectedExtension {
    param([byte[]]$Bytes)

    if ($Bytes.Length -ge 8 -and [BitConverter]::ToString($Bytes, 0, 8) -eq '89-50-4E-47-0D-0A-1A-0A') { return '.png' }
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xff -and $Bytes[1] -eq 0xd8 -and $Bytes[2] -eq 0xff) { return '.jpg' }
    if ($Bytes.Length -ge 4) {
        $ascii4 = [Text.Encoding]::ASCII.GetString($Bytes, 0, 4)
        if ($ascii4 -eq 'DDS ') { return '.dds' }
        if ($ascii4 -eq 'RIFF') { return '.riff' }
        if ($ascii4 -eq 'OggS') { return '.ogg' }
        if ($ascii4 -eq 'FSB5') { return '.fsb' }
        if ($ascii4 -eq 'PK' + [char]3 + [char]4) { return '.zip' }
        if ($ascii4 -eq 'PVR' + [char]3) { return '.pvr' }
    }
    if ($Bytes.Length -ge 8 -and [BitConverter]::ToString($Bytes, 0, 8) -eq 'AB-4B-54-58-20-31-31-BB') { return '.ktx' }
    if ($Bytes.Length -ge 7 -and [Text.Encoding]::ASCII.GetString($Bytes, 0, 7) -eq 'UnityFS') { return '.unity3d' }
    if ($Bytes.Length -ge 4 -and $Bytes[0] -eq 0x34 -and $Bytes[1] -eq 0x80 -and $Bytes[2] -eq 0xc8 -and $Bytes[3] -eq 0xbb) { return '.mesh' }
    return '.bin'
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$files = if ([IO.File]::Exists($resolvedInput)) {
    @(Get-Item -LiteralPath $resolvedInput)
} else {
    @(Get-ChildItem -LiteralPath $resolvedInput -Filter '*.pcbin' -File -Recurse)
}

[IO.Directory]::CreateDirectory($OutputPath) | Out-Null
$manifest = [Collections.Generic.List[object]]::new()

foreach ($file in $files) {
    try {
        $raw = [IO.File]::ReadAllBytes($file.FullName)
        if ($raw.Length -lt 9) { throw 'File is too short for a cloudfilesys header.' }

        $magic = [Text.Encoding]::ASCII.GetString($raw, 0, 2)
        if ($magic -notin @('PC', 'AC')) { throw "Unsupported cloudfilesys magic: $magic" }
        if ($raw[2] -lt 1 -or $raw[2] -gt 56) { throw "Invalid prefix exponent: $($raw[2])" }

        # AC/PC/XC carry a four-byte checksum after the four-byte dataheader.
        $headerLength = 8
        $contentLength = $raw.Length - $headerLength
        $content = [byte[]]::new($contentLength)
        [Array]::Copy($raw, $headerLength, $content, 0, $contentLength)
        $protectedLength = [Math]::Min([UInt64]$contentLength, ([UInt64]128 -shl ($raw[2] - 1)))
        $aesLength = [int]($protectedLength -band (-bnot 15))
        $key = Get-CloudFileKey -Length ([UInt32]$contentLength) -HeaderByte $raw[3]

        if ($aesLength -gt 0) {
            $aes = [Security.Cryptography.Aes]::Create()
            try {
                $aes.Mode = [Security.Cryptography.CipherMode]::ECB
                $aes.Padding = [Security.Cryptography.PaddingMode]::None
                $aes.Key = $key
                $decryptor = $aes.CreateDecryptor()
                try {
                    $plain = $decryptor.TransformFinalBlock($content, 0, $aesLength)
                    [Array]::Copy($plain, 0, $content, 0, $plain.Length)
                } finally {
                    $decryptor.Dispose()
                }
            } finally {
                $aes.Dispose()
            }
        }

        # The engine applies this only to the non-block-aligned part of the protected prefix.
        $tailLength = [int]$protectedLength - $aesLength
        $seed = [UInt32]($contentLength + $raw[3])
        for ($i = 0; $i -lt $tailLength; $i++) {
            $destination = $aesLength + $i
            $mask = if ($i -lt $aesLength) {
                ([int]$content[$i] + $i + $seed) -band 0xff
            } else {
                ($i + $seed) -band 0xff
            }
            $content[$destination] = [byte]($content[$destination] -bxor $mask)
        }

        # cloudfilesys probes compression by reversing/XORing the first 64 bytes.
        $probeLength = [Math]::Min(64, $content.Length)
        $probe = [byte[]]::new($probeLength)
        for ($i = 0; $i -lt $probeLength; $i++) {
            $probe[$i] = [byte]($content[$probeLength - 1 - $i] -bxor 0x5a)
        }
        [Array]::Copy($probe, 0, $content, 0, $probeLength)

        $compressionMagic = if ($content.Length -ge 4) { [Text.Encoding]::ASCII.GetString($content, 0, 4) } else { '' }
        if ($compressionMagic -eq 'DTSZ') {
            $payload = [byte[]]::new($content.Length - 4)
            [Array]::Copy($content, 4, $payload, 0, $payload.Length)
            $content = $payload
            $extension = '.zst'
        } elseif ($compressionMagic -eq 'ENNO') {
            $payload = [byte[]]::new($content.Length - 4)
            [Array]::Copy($content, 4, $payload, 0, $payload.Length)
            $content = $payload
            $extension = Get-DetectedExtension -Bytes $content
        } else {
            $extension = '.bin'
        }
        $relative = [IO.Path]::GetRelativePath($resolvedInput, $file.FullName)
        if ([IO.File]::Exists($resolvedInput)) { $relative = $file.Name }
        $relativeDirectory = [IO.Path]::GetDirectoryName($relative)
        $baseName = [IO.Path]::GetFileNameWithoutExtension($relative)
        $destinationDirectory = if ([string]::IsNullOrEmpty($relativeDirectory)) { $OutputPath } else { Join-Path $OutputPath $relativeDirectory }
        [IO.Directory]::CreateDirectory($destinationDirectory) | Out-Null
        $destinationPath = Join-Path $destinationDirectory ($baseName + $extension)
        [IO.File]::WriteAllBytes($destinationPath, $content)

        $manifest.Add([pscustomobject]@{
            Source = $file.FullName
            Output = $destinationPath
            Magic = $magic
            ContentLength = $contentLength
            ProtectedLength = $protectedLength
            AesLength = $aesLength
            KeyHex = [BitConverter]::ToString($key).Replace('-', '').ToLowerInvariant()
            CompressionMagic = $compressionMagic
            Type = $extension.TrimStart('.')
            Status = 'ok'
            Error = ''
        })
    } catch {
        $manifest.Add([pscustomobject]@{
            Source = $file.FullName
            Output = ''
            Magic = ''
            ContentLength = 0
            ProtectedLength = 0
            AesLength = 0
            KeyHex = ''
            CompressionMagic = ''
            Type = ''
            Status = 'error'
            Error = $_.Exception.Message
        })
    }
}

$manifestPath = Join-Path $OutputPath 'manifest.csv'
$manifest | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8
$manifest | Group-Object Type, Status | ForEach-Object {
    [pscustomobject]@{ Group = $_.Name; Count = $_.Count }
} | Format-Table -AutoSize
Write-Host "Manifest: $manifestPath"
