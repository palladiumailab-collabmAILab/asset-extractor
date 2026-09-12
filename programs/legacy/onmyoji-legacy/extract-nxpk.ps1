param([Parameter(Mandatory)][string]$InputFile,[Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$stream=[IO.File]::OpenRead($InputFile)
$reader=[IO.BinaryReader]::new($stream)
$rows=[Collections.Generic.List[object]]::new()
try {
 if([Text.Encoding]::ASCII.GetString($reader.ReadBytes(4)) -ne 'NXPK'){throw 'Not NXPK'}
 $count=$reader.ReadUInt32()
 $null=$reader.ReadBytes(12)
 $index=$reader.ReadUInt32()
 if($index+32L*$count -gt $stream.Length){throw 'Index exceeds file'}
 $stream.Position=$index
 $entries=@(for($i=0;$i -lt $count;$i++){ ,@($reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32(),$reader.ReadUInt32()) })
 for($i=0;$i -lt $count;$i++){
  $e=$entries[$i]; $status='ok'; $name=''
  try {
   if([long]$e[2]+$e[3] -gt $stream.Length -or $e[3] -gt 536870912){throw 'Invalid entry bounds'}
   $stream.Position=$e[2]; $data=$reader.ReadBytes($e[3])
   if($e[7] -band 0x10000){for($j=0;$j -lt [Math]::Min(128,$data.Length);$j++){$data[$j]=$data[$j] -bxor ((150+$j)%256)}}
   if(($e[7] -band 0xffff) -eq 1){$ms=[IO.MemoryStream]::new($data,$false);$z=[IO.Compression.ZLibStream]::new($ms,[IO.Compression.CompressionMode]::Decompress);$out=[IO.MemoryStream]::new();try{$z.CopyTo($out);$data=$out.ToArray()}finally{$z.Dispose();$ms.Dispose();$out.Dispose()}}
   elseif(($e[7] -band 0xffff) -ne 0){throw 'Unsupported compression'}
   if($data.Length -ne $e[4]){throw 'Uncompressed length mismatch'}
   $magic=[Text.Encoding]::ASCII.GetString($data,0,[Math]::Min(16,$data.Length));$ext='bin'
   if($data.Length -ge 4 -and $data[0] -eq 137 -and $magic.Substring(1,3) -eq 'PNG'){$ext='png'}
   elseif($data.Length -ge 3 -and $data[0] -eq 255 -and $data[1] -eq 216 -and $data[2] -eq 255){$ext='jpg'}
   elseif($magic -match '^.KTX'){$ext='ktx'} elseif($magic.StartsWith('DDS ')){$ext='dds'} elseif($magic.StartsWith('PVR')){$ext='pvr'} elseif($magic.StartsWith('OggS')){$ext='ogg'} elseif($magic.StartsWith('FSB')){$ext='fsb'} elseif($magic.StartsWith('RIFF')){$ext='riff'} elseif($magic -match '^....ftyp'){$ext='mp4'} elseif($magic.StartsWith('<?xml')){$ext='xml'} elseif($magic.StartsWith('{')){$ext='json'}
   $name=('{0:D7}_{1:X8}.{2}' -f $i,$e[0],$ext);[IO.File]::WriteAllBytes((Join-Path $OutputDirectory $name),$data)
  }catch{$status=$_.Exception.Message}
  $rows.Add([pscustomobject]@{Index=$i;File=$name;Offset=$e[2];PackedSize=$e[3];Size=$e[4];Flags=$e[7];Status=$status})
 }
}finally{$reader.Dispose();$stream.Dispose()}
$rows | Export-Csv (Join-Path $OutputDirectory 'manifest.csv') -NoTypeInformation -Encoding utf8
$rows | Group-Object Status | Select-Object Name,Count
