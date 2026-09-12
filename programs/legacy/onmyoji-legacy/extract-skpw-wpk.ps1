param(
    [Parameter(Mandatory)][string]$IndexFile,
    [Parameter(Mandatory)][string]$WpkFile,
    [Parameter(Mandatory)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

function ConvertTo-Hex([byte[]]$Bytes) {
    return ($Bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Get-PayloadType([byte[]]$Bytes) {
    if ($Bytes.Length -lt 4) { return 'short' }
    $offset = if ($Bytes[0] -eq 0x50 -and $Bytes[1] -eq 0x43 -and $Bytes[2] -eq 0x01 -and $Bytes[3] -eq 0x00) { 4 } else { 0 }
    if ($Bytes.Length -lt ($offset + 4)) { return 'short' }
    if ($Bytes[$offset] -eq 0x89 -and $Bytes[$offset + 1] -eq 0x50 -and $Bytes[$offset + 2] -eq 0x4e -and $Bytes[$offset + 3] -eq 0x47) { return 'png' }
    if ($Bytes[$offset] -eq 0xff -and $Bytes[$offset + 1] -eq 0xd8 -and $Bytes[$offset + 2] -eq 0xff) { return 'jpg' }
    if ($Bytes[$offset] -eq 0x44 -and $Bytes[$offset + 1] -eq 0x44 -and $Bytes[$offset + 2] -eq 0x53 -and $Bytes[$offset + 3] -eq 0x20) { return 'dds' }
    if ($Bytes[$offset] -eq 0xab -and $Bytes[$offset + 1] -eq 0x4b -and $Bytes[$offset + 2] -eq 0x54 -and $Bytes[$offset + 3] -eq 0x58) { return 'ktx' }
    if ($Bytes[$offset] -eq 0x50 -and $Bytes[$offset + 1] -eq 0x4b) { return 'zip' }
    if ($Bytes[$offset] -eq 0x1f -and $Bytes[$offset + 1] -eq 0x8b) { return 'gzip' }
    if ($Bytes[$offset] -eq 0x78 -and $Bytes[$offset + 1] -in 0x01,0x5e,0x9c,0xda) { return 'zlib-candidate' }
    return 'unknown'
}

$indexStream = [IO.File]::OpenRead($IndexFile)
$indexReader = [IO.BinaryReader]::new($indexStream)
try {
    if ([Text.Encoding]::ASCII.GetString($indexReader.ReadBytes(4)) -ne 'SKPW') { throw 'Not an SKPW index' }
    $opaqueHeader = $indexReader.ReadUInt32()
    $zero = $indexReader.ReadUInt32()
    $count = $indexReader.ReadUInt32()
    $fixed = $indexReader.ReadBytes(16)
    $expectedSize = 0x20L + 0x1cL * $count + 4L
    if ($indexStream.Length -ne $expectedSize) { throw "Unexpected IDX size: $($indexStream.Length), expected $expectedSize" }

    $entries = @()
    for ($i = 0; $i -lt $count; $i++) {
        $hashBytes = $indexReader.ReadBytes(16)
        $length = $indexReader.ReadUInt32()
        $offset = $indexReader.ReadUInt32()
        $mode = $indexReader.ReadUInt16()
        $opaque = $indexReader.ReadUInt16()
        $entries += [pscustomobject]@{
            Index = $i
            Hash = ConvertTo-Hex $hashBytes
            Length = [uint64]$length
            Offset = [uint64]$offset
            Mode = $mode
            Opaque = $opaque
        }
    }
    $trailer = $indexReader.ReadUInt32()
} finally {
    $indexReader.Dispose()
    $indexStream.Dispose()
}

$wpkStream = [IO.File]::OpenRead($WpkFile)
$wpkReader = [IO.BinaryReader]::new($wpkStream)
$rows = [Collections.Generic.List[object]]::new()
try {
    $ordered = @($entries | Sort-Object Offset, Index)
    for ($rank = 0; $rank -lt $ordered.Count; $rank++) {
        $entry = $ordered[$rank]
        $status = 'ok'
        $fileName = ''
        $payloadType = ''
        $pcHeader = $false
        $nextOffset = if ($rank + 1 -lt $ordered.Count) { [uint64]$ordered[$rank + 1].Offset } else { [uint64]$wpkStream.Length }
        try {
            if ($entry.Offset + $entry.Length -gt $wpkStream.Length) { throw 'Entry exceeds WPK size' }
            $wpkStream.Position = [int64]$entry.Offset
            $data = $wpkReader.ReadBytes([int]$entry.Length)
            if ($data.Length -ne $entry.Length) { throw 'Short read' }
            $pcHeader = $data.Length -ge 4 -and $data[0] -eq 0x50 -and $data[1] -eq 0x43 -and $data[2] -eq 0x01 -and $data[3] -eq 0x00
            if (-not $pcHeader) { throw 'Missing PC 01 00 header' }
            $payloadType = Get-PayloadType $data
            $fileName = ('{0:D5}_{1}_{2:X8}.pcbin' -f $entry.Index, $entry.Hash, $entry.Offset)
            [IO.File]::WriteAllBytes((Join-Path $OutputDirectory $fileName), $data)
        } catch {
            $status = $_.Exception.Message
        }
        $rows.Add([pscustomobject]@{
            Index = $entry.Index
            Hash = $entry.Hash
            Offset = $entry.Offset
            Length = $entry.Length
            NextOffset = $nextOffset
            AlignedSpan = $nextOffset - $entry.Offset
            Mode = $entry.Mode
            Opaque = $entry.Opaque
            PcHeader = $pcHeader
            PayloadType = $payloadType
            File = $fileName
            Status = $status
        })
    }
} finally {
    $wpkReader.Dispose()
    $wpkStream.Dispose()
}

$rows | Sort-Object Index | Export-Csv (Join-Path $OutputDirectory 'manifest.csv') -NoTypeInformation -Encoding utf8
[pscustomobject]@{
    IndexFile = $IndexFile
    WpkFile = $WpkFile
    HeaderValue = ('0x{0:X8}' -f $opaqueHeader)
    HeaderZero = $zero
    Count = $count
    Trailer = ('0x{0:X8}' -f $trailer)
    WpkBytes = (Get-Item -LiteralPath $WpkFile).Length
    Errors = @($rows | Where-Object Status -ne 'ok').Count
} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'archive-info.json') -Encoding utf8

$rows | Group-Object Status | Select-Object Name, Count
