[CmdletBinding()]
param(
    [switch]$SkipDocker
)

Set-StrictMode -Version Latest
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repositoryRoot
try {
    Invoke-Checked 'unstaged whitespace check' { git diff --check }
    Invoke-Checked 'staged whitespace check' { git diff --cached --check }
    Invoke-Checked 'pre-commit syntax check' { bash -n .githooks/pre-commit }
    Invoke-Checked 'pre-commit behavior tests' { bash tests/test-pre-commit.sh }

    $hookEntry = (& git ls-files -s -- .githooks/pre-commit)
    if ($LASTEXITCODE -ne 0 -or -not $hookEntry) {
        throw 'Unable to inspect the tracked pre-commit hook.'
    }
    $hookMode = ($hookEntry -split '\s+')[0]
    if ($hookMode -ne '100755') {
        throw "Tracked pre-commit hook must be executable (100755); found $hookMode."
    }

    $agentsSize = (Get-Item -LiteralPath AGENTS.md).Length
    if ($agentsSize -gt 32768) {
        throw "AGENTS.md exceeds the default 32 KiB project instruction limit: $agentsSize bytes."
    }

    if ($SkipDocker) {
        Invoke-Checked 'skill validation' { python scripts/validate-skills.py skills }
    }
    else {
        Invoke-Checked 'Docker availability check' { docker info --format '{{.ServerVersion}}' }
        $mount = "type=bind,source=$repositoryRoot,target=/workspace,readonly"
        Invoke-Checked 'containerized skill validation' {
            docker run --rm --mount $mount python:3.13-slim sh -c 'python -m pip install --root-user-action=ignore --disable-pip-version-check --no-cache-dir --quiet -r /workspace/requirements-dev.txt && python /workspace/scripts/validate-skills.py /workspace/skills'
        }
    }

    Invoke-Checked 'asset extractor tests' { python -m unittest discover -s development/tests -t . }

    Write-Output 'Harness validation passed.'
}
finally {
    Pop-Location
}
