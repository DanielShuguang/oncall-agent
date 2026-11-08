# Windows 无 make 时的等价命令
# 用法：pwsh -File scripts/dev.ps1 api
#
# 本机 Docker 有两种形态：
#   1) 装了 Docker Desktop  -> 直接用 up/down/logs
#   2) 只有 WSL + docker.io -> 用 docker-up/docker-down/docker-ps/docker-logs
#      （见 scripts/wsl-setup.sh）

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'up', 'down', 'logs', 'migrate', 'install', 'api', 'web', 'fmt', 'lint', 'test', 'eval',
        'seed', 'clean', 'check',
        'docker-up', 'docker-down', 'docker-ps', 'docker-logs'
    )]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function ConvertTo-WslPath([string]$WindowsPath) {
    $drive = $WindowsPath.Substring(0, 1).ToLower()
    $rest = $WindowsPath.Substring(2) -replace '\\', '/'
    return "/mnt/$drive$rest"
}

function Invoke-WslDocker([string]$Args) {
    $wslRoot = ConvertTo-WslPath $root
    # 本机 WSL 没有 systemd，dockerd 不会自启；先确保守护进程在线
    wsl.exe -d Ubuntu -u root -- bash /mnt/e/workspace/github/oncall/scripts/wsl-docker.sh ensure
    wsl.exe -d Ubuntu -u root -- bash -lc "cd '$wslRoot' && docker compose $Args"
}

switch ($Target) {
    'up' { Push-Location $root; docker compose up -d; Pop-Location }
    'down' { Push-Location $root; docker compose down; Pop-Location }
    'logs' { Push-Location $root; docker compose logs -f --tail=100; Pop-Location }
    'migrate' { Push-Location "$root\server"; uv run alembic upgrade head; Pop-Location }

    'docker-up' { Invoke-Step 'wsl: docker compose up -d' { Invoke-WslDocker 'up -d' } }
    'docker-down' { Invoke-Step 'wsl: docker compose down' { Invoke-WslDocker 'down' } }
    'docker-ps' { Invoke-Step 'wsl: docker compose ps' { Invoke-WslDocker 'ps' } }
    'docker-logs' { Invoke-WslDocker 'logs -f --tail=100' }

    'install' {
        Invoke-Step 'uv sync' { Push-Location "$root\server"; uv sync --all-extras; Pop-Location }
        Invoke-Step 'pnpm install' { Push-Location "$root\web"; pnpm install; Pop-Location }
    }
    'api' { Push-Location "$root\server"; uv run uvicorn app.main:app --reload --port 8000; Pop-Location }
    'web' { Push-Location "$root\web"; pnpm dev; Pop-Location }
    'fmt' {
        Push-Location "$root\server"; uv run ruff format .; uv run ruff check --fix .; Pop-Location
        Push-Location "$root\web"; pnpm exec oxfmt; Pop-Location
    }
    'lint' {
        Push-Location "$root\server"; uv run ruff check .; uv run ruff format --check .; uv run mypy app; Pop-Location
        Push-Location "$root\web"; pnpm exec oxlint; pnpm exec oxfmt --check; Pop-Location
    }
    'test' {
        Push-Location "$root\server"; uv run pytest -q; Pop-Location
        Push-Location "$root\web"; pnpm test; Pop-Location
    }
    'eval' { Push-Location "$root\server"; uv run python -m app.eval.runner; Pop-Location }
    'seed' { Push-Location "$root\server"; uv run python -m app.seed.generate --db; Pop-Location }
    'clean' {
        Remove-Item -Recurse -Force "$root\web\dist" -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force "$root\server\.pytest_cache" -ErrorAction SilentlyContinue
    }
    'check' {
        & $PSScriptRoot\dev.ps1 lint
        & $PSScriptRoot\dev.ps1 test
    }
}
