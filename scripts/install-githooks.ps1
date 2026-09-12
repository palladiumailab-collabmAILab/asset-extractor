[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$resolvedRepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$gitPath = Join-Path $resolvedRepositoryRoot '.git'
$hooksPath = Join-Path $resolvedRepositoryRoot '.githooks'
$hookFile = Join-Path $hooksPath 'pre-commit'

if (-not (Test-Path -LiteralPath $gitPath)) {
    throw "Not a Git repository: $resolvedRepositoryRoot"
}

if (-not (Test-Path -LiteralPath $hookFile -PathType Leaf)) {
    throw "Hook file was not found: $hookFile"
}

& git -C $resolvedRepositoryRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw 'git config core.hooksPath failed.'
}

Write-Output "Installed .githooks for $resolvedRepositoryRoot"
