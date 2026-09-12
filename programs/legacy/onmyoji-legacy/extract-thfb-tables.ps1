param(
    [Parameter(Mandatory)][string[]]$InputDirectories,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$SummaryFile
)

$ErrorActionPreference = 'Stop'
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$summary = [Collections.Generic.List[object]]::new()

foreach ($file in Get-ChildItem -LiteralPath $InputDirectories -File | Where-Object Extension -in '.thi', '.thx', '.thp') {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $magic = if ($bytes.Length -ge 4) { [Text.Encoding]::ASCII.GetString($bytes, 0, 4) } else { '' }
    $status = 'ok'
    $variant = ''
    $count = 0
    $marker = ''
    $outDir = Join-Path $OutputDirectory ($file.Directory.Name + '-' + $file.BaseName + $file.Extension.TrimStart('.'))
    [IO.Directory]::CreateDirectory($outDir) | Out-Null

    try {
        if ($magic -ne 'THFB') { throw 'Not THFB' }
        if ($bytes.Length -lt 0x78) { throw 'Header too short' }
        $marker = (($bytes[0x20..0x27] | ForEach-Object { $_.ToString('x2') }) -join '')
        $count = [BitConverter]::ToUInt32($bytes, 0x74)
        $sectionAEnd = 0x78L + 8L * $count
        if ($sectionAEnd -gt $bytes.Length) { throw 'Section A exceeds file size' }

        $rows = [Collections.Generic.List[object]]::new()
        for ($i = 0; $i -lt $count; $i++) {
            $offset = 0x78 + 8 * $i
            $rows.Add([ordered]@{
                Index = $i
                A0 = [BitConverter]::ToUInt32($bytes, $offset)
                A1 = [BitConverter]::ToUInt32($bytes, $offset + 4)
            })
        }

        if ($file.Extension -eq '.thx') {
            $expected = 0x80L + 32L * $count
            if ($bytes.Length -ne $expected) { throw "Unexpected THX size: $($bytes.Length), expected $expected" }
            $sectionBHeader = [int]$sectionAEnd
            $bZero = [BitConverter]::ToUInt32($bytes, $sectionBHeader)
            $bCount = [BitConverter]::ToUInt32($bytes, $sectionBHeader + 4)
            if ($bZero -ne 0 -or $bCount -ne $count) { throw 'Invalid THX section B header' }
            for ($i = 0; $i -lt $count; $i++) {
                $offset = $sectionBHeader + 8 + 24 * $i
                for ($j = 0; $j -lt 6; $j++) { $rows[$i]["B$j"] = [BitConverter]::ToUInt32($bytes, $offset + 4 * $j) }
            }
            $variant = 'thx-fixed-24'
        } elseif ($file.Extension -eq '.thi') {
            $variantA = 0x7cL + 12L * $count
            $variantB = 0x80L + 12L * $count
            if ($bytes.Length -eq $variantA) {
                $sectionB = [int]$sectionAEnd
                $bCount = [BitConverter]::ToUInt32($bytes, $sectionB)
                if ($bCount -ne $count) { throw 'Invalid THI variant A count' }
                $valuesOffset = $sectionB + 4
                $variant = 'thi-a'
            } elseif ($bytes.Length -eq $variantB) {
                $sectionB = [int]$sectionAEnd
                $bZero = [BitConverter]::ToUInt32($bytes, $sectionB)
                $bCount = [BitConverter]::ToUInt32($bytes, $sectionB + 4)
                if ($bZero -ne 0 -or $bCount -ne $count) { throw 'Invalid THI variant B header' }
                $valuesOffset = $sectionB + 8
                $variant = 'thi-b'
            } else {
                throw "Unexpected THI size: $($bytes.Length)"
            }
            for ($i = 0; $i -lt $count; $i++) { $rows[$i]['B0'] = [BitConverter]::ToUInt32($bytes, $valuesOffset + 4 * $i) }
        } else {
            $variant = 'thp-variable-tail'
            $tailLength = $bytes.Length - [int]$sectionAEnd
            if ($tailLength -gt 0) {
                $tail = [byte[]]::new($tailLength)
                [Array]::Copy($bytes, [int]$sectionAEnd, $tail, 0, $tailLength)
                [IO.File]::WriteAllBytes((Join-Path $outDir 'variable-tail.bin'), $tail)
            }
        }

        $rows | ForEach-Object { [pscustomobject]$_ } | Export-Csv (Join-Path $outDir 'records.csv') -NoTypeInformation -Encoding utf8
    } catch {
        $status = $_.Exception.Message
    }

    $summary.Add([pscustomobject]@{
        File = $file.FullName
        Bytes = $file.Length
        Magic = $magic
        Marker = $marker
        Count = $count
        Variant = $variant
        Status = $status
        Output = $outDir
    })
}

$summary | Export-Csv $SummaryFile -NoTypeInformation -Encoding utf8
$summary | Group-Object Status | Select-Object Name, Count
