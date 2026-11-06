# 一键构建 hub.exe（PyInstaller onedir）
# 产物：dist\hub\hub.exe + dist\hub\.hub\（把整个 dist\hub 目录放到自己的数据仓库根目录即可运行）
# 依赖：Python 3.10+、PyInstaller（pip install pyinstaller）
# 用法：powershell -ExecutionPolicy Bypass -File hub\build.ps1

param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$build = Join-Path $repo ".build"
$dist = Join-Path $repo "dist"

Write-Host "[1/4] 检查 PyInstaller..." -ForegroundColor Cyan
& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未安装 PyInstaller，请先执行: $Python -m pip install pyinstaller" -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] 打包中（onedir，内容目录 .hub）..." -ForegroundColor Cyan
$env:PYINSTALLER_CONFIG_DIR = Join-Path $build "pyinstaller-config"
$hidden = @(
    "--hidden-import", "pages.douyin",
    "--hidden-import", "pages.xhs",
    "--hidden-import", "core.paths",
    "--hidden-import", "dash",
    "--hidden-import", "core.privacy",
    "--hidden-import", "core.douyin",
    "--hidden-import", "core.douyin_auth",
    "--hidden-import", "core.douyin_sync",
    "--hidden-import", "core.browser",
    "--hidden-import", "core.xhs",
    "--hidden-import", "core.xhs_sync",
    "--hidden-import", "core.xhs_auth",
    "--hidden-import", "core.loginkey",
    "--hidden-import", "core.xlsx",
    "--collect-submodules", "websockets",
    "--exclude-module", "numpy",
    "--exclude-module", "PIL",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "cryptography"
)
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name hub `
    --contents-directory ".hub" `
    @hidden `
    --distpath $dist `
    --workpath (Join-Path $build "work-hub") `
    --specpath $build `
    (Join-Path $here "hub.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host "[3/4] 校验产物..." -ForegroundColor Cyan
$exe = Join-Path $dist "hub\hub.exe"
$content = Join-Path $dist "hub\.hub"
if (-not (Test-Path $exe)) { throw "构建产物缺失：$exe" }
$n = (Get-ChildItem $content -Recurse -File | Measure-Object).Count
if ($n -lt 900) { throw "产物不完整（$n 个文件）" }

Write-Host "[4/4] 完成" -ForegroundColor Green
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "产物：$dist\hub\（hub.exe 约 $mb MB，运行时 $n 个文件）"
Write-Host "用法：把 dist\hub 整个目录放进数据仓库根目录，运行 hub\hub.exe；或设置 HUB_ROOT 后运行。"
