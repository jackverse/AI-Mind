param(
    [int]$Port = 8765,
    [switch]$Lan
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$hostArg = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host '没找到 python，请先安装 Python 3.10+ 或从桌面 hub 的 .hub\ 目录里找。' -ForegroundColor Red
    exit 1
}

Write-Host "启动 hub-web：http://127.0.0.1:$Port/" -ForegroundColor Cyan
& $py.Source "$here\server.py" --port $Port --host $hostArg --open
