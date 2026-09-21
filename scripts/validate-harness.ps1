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

function Invoke-PythonValidation {
    Invoke-Checked 'package install' { python -m pip install --disable-pip-version-check --no-deps . }
    Invoke-Checked 'package metadata smoke' {
        python -c "import importlib.metadata as m; import asset_extractor; assert m.version('asset-extractor') == asset_extractor.__version__"
    }
    Invoke-Checked 'console script smoke' { asset-extractor --help | Out-Null }
    Invoke-Checked 'skill validation' { python scripts/validate-skills.py skills }
    Invoke-Checked 'canonical documentation path validation' { python scripts/check-canonical-doc-paths.py }
    Invoke-Checked 'asset extractor tests' { coverage run --branch --source=asset_extractor -m unittest discover -s development/tests -t . }
    Invoke-Checked 'coverage threshold' { coverage report --fail-under=55 }
    Invoke-Checked 'coverage JSON' { coverage json -o coverage.json }
    Invoke-Checked 'critical coverage baseline' { python scripts/check-critical-coverage.py coverage.json }
    Invoke-Checked 'Ruff lint' { ruff check programs scripts development/tests }
    Invoke-Checked 'Ruff format' { ruff format --check programs scripts development/tests }
    Invoke-Checked 'mypy' { mypy }
    Invoke-Checked 'schema validation' {
        python scripts/validate-schemas.py `
            --manifest visual-reference-evidence=development/config/character-asset-evidence-20260914.json `
            --manifest visual-reference-evidence=development/config/kainin-asset-variants-20260914.json
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
        Invoke-PythonValidation
    }
    else {
        Invoke-Checked 'Docker availability check' { docker info --format '{{.ServerVersion}}' }
        $imageName = "asset-extractor-validation:$PID"
        Invoke-Checked 'Docker validation image build' { docker build --tag $imageName . }
        try {
            Invoke-Checked 'containerized repository validation' { docker run --rm $imageName }
        }
        finally {
            docker image rm $imageName | Out-Null
        }
    }

    Write-Output 'Harness validation passed.'
}
finally {
    Pop-Location
}
