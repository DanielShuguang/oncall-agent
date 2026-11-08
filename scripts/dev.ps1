# Windows 无 make 时的等价命令
# 用法：pwsh -File scripts/dev.ps1 api

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('up', 'down', 'logs', 'install', 'api', 'web', 'fmt', 'lint', 'test', 'eval', 'seed', 'clean', 'check')]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    'up' { Invoke-Step 'docker compose up -d' { Push-Location $root; docker compose up -d; Pop-Location } }
    'down' { Invoke-Step 'docker compose down' { Push-Location $root; docker compose down; Pop-Location } }
    'logs' { Push-Location $root; docker compose logs -f --tail=100; Pop-Location }
    'install' {
        Invoke-Step 'uv sync' { Push-Location "$root\server"; uv sync --all-extras; Pop-Location }
        Invoke-Step 'pnpm install' { Push-Location "$root\web"; pnpm install; Pop-Location }
    }
    'api' { Push-Location "$root\server"; uv run uvicorn app.main:app --reload --port 8000; Pop-Location }
    'web' { Push-Location "$root\web"; pnpm dev; Pop-Location }
    'fmt' {
        Push-Location "$root\server"; uv run ruff format .; uv run ruff check --fix .; Pop-Location
        Push-Location "$root\web"; pnpm biome format --write .; Pop-Location
    }
    'lint' {
        Push-Location "$root\server"; uv run ruff check .; uv run mypy app; Pop-Location
        Push-Location "$root\web"; pnpm biome check .; Pop-Location
    }
    'test' {
        Push-Location "$root\server"; uv run pytest -q; Pop-Location
        Push-Location "$root\web"; pnpm test; Pop-Location
    }
    'eval' { Push-Location "$root\server"; uv run python -m app.eval.runner; Pop-Location }
    'seed' { Push-Location "$root\server"; uv run python -m app.seed.generate; Pop-Location }
    'clean' {
        Remove-Item -Recurse -Force "$root\web\dist" -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force "$root\server\.pytest_cache" -ErrorAction SilentlyContinue
    }
    'check' { & $PSScriptRoot\dev.ps1 lint; & $PSScriptRoot\dev.ps1 test }
}
