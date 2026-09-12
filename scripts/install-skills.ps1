[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CodexSkillsRoot,
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$resolvedRepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$sourceRoot = Join-Path $resolvedRepositoryRoot 'skills'
$resolvedSkillsRoot = (Resolve-Path -LiteralPath $CodexSkillsRoot).Path

if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Skills directory was not found: $sourceRoot"
}

$skillDirectories = @(Get-ChildItem -LiteralPath $sourceRoot -Directory)
if ($skillDirectories.Count -eq 0) {
    throw "No skill directories were found: $sourceRoot"
}

$existing = @(
    $skillDirectories |
        Where-Object { Test-Path -LiteralPath (Join-Path $resolvedSkillsRoot $_.Name) } |
        Select-Object -ExpandProperty Name
)
if ($existing.Count -gt 0) {
    $names = $existing -join ', '
    throw "Refusing to overwrite existing skill directories: $names"
}

foreach ($skillDirectory in $skillDirectories) {
    Copy-Item -LiteralPath $skillDirectory.FullName -Destination (Join-Path $resolvedSkillsRoot $skillDirectory.Name) -Recurse
    Write-Output "Installed skill: $($skillDirectory.Name)"
}
