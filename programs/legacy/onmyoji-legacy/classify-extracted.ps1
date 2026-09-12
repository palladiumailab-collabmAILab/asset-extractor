$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$summary=@()
foreach($manifest in Get-ChildItem "$root\extracted-npk" -Recurse -Filter manifest.csv){
 $rows=Import-Csv $manifest.FullName
 foreach($row in $rows){
  if($row.Status -ne 'ok' -or -not $row.File.EndsWith('.bin')){continue}
  $path=Join-Path $manifest.DirectoryName $row.File
  $s=[IO.File]::OpenRead($path);$b=[byte[]]::new(16);$n=$s.Read($b,0,16);$s.Dispose();$ext=$null
  if($n -ge 4 -and $b[0] -eq 137 -and $b[1] -eq 80 -and $b[2] -eq 78 -and $b[3] -eq 71){$ext='png'}
  elseif($n -ge 3 -and $b[0] -eq 255 -and $b[1] -eq 216 -and $b[2] -eq 255){$ext='jpg'}
  elseif($n -ge 4 -and $b[0] -eq 0x34 -and $b[1] -eq 0x80 -and $b[2] -eq 0xc8 -and $b[3] -eq 0xbb){$ext='mesh'}
  if($ext){$new=[IO.Path]::ChangeExtension($row.File,$ext);Move-Item -LiteralPath $path -Destination (Join-Path $manifest.DirectoryName $new);$row.File=$new}
 }
 $rows | Export-Csv $manifest.FullName -NoTypeInformation -Encoding utf8
 $summary += [pscustomobject]@{Archive=$manifest.Directory.Name;Entries=$rows.Count;Errors=@($rows|Where-Object Status -ne 'ok').Count}
}
$summary | Export-Csv "$root\reports\npk-summary.csv" -NoTypeInformation -Encoding utf8
Get-ChildItem "$root\extracted-npk" -Recurse -File | Where-Object Extension -ne '.csv' | Group-Object Extension | ForEach-Object {[pscustomobject]@{Extension=$_.Name;Count=$_.Count;Bytes=($_.Group|Measure-Object Length -Sum).Sum}} | Export-Csv "$root\reports\npk-types.csv" -NoTypeInformation -Encoding utf8
