param(
    [Parameter(Mandatory)][string]$InputFile,
    [Parameter(Mandatory)][string]$OutputCsv
)

$ErrorActionPreference = 'Stop'
$bytes = [IO.File]::ReadAllBytes($InputFile)
if ($bytes.Length -lt 20 -or (($bytes.Length - 20) % 20) -ne 0) { throw 'Unexpected g37 table size' }

function Read-U32BE([byte[]]$Data, [int]$Offset) {
    return [uint32](
        ([uint32]$Data[$Offset] -shl 24) -bor
        ([uint32]$Data[$Offset + 1] -shl 16) -bor
        ([uint32]$Data[$Offset + 2] -shl 8) -bor
        [uint32]$Data[$Offset + 3]
    )
}

$count = [int](($bytes.Length - 20) / 20)
$rows = [Collections.Generic.List[object]]::new($count)
for ($i = 0; $i -lt $count; $i++) {
    $offset = 16 + 20 * $i
    $rows.Add([pscustomobject]@{
        Index = $i
        Value0 = Read-U32BE $bytes $offset
        Value1 = Read-U32BE $bytes ($offset + 4)
        Value2 = Read-U32BE $bytes ($offset + 8)
        Value3 = Read-U32BE $bytes ($offset + 12)
        Value4 = Read-U32BE $bytes ($offset + 16)
    })
}

$rows | Export-Csv $OutputCsv -NoTypeInformation -Encoding utf8
[pscustomobject]@{
    Records = $count
    Prefix0 = Read-U32BE $bytes 0
    Trailer = Read-U32BE $bytes ($bytes.Length - 4)
}
