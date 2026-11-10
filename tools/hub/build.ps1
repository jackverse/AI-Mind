# 一键构建 hub.exe（onedir，产物放仓库根目录：hub.exe + .hub\）
# 依赖：Python 3.8+、PyInstaller（pip install pyinstaller）
# 用法：powershell -ExecutionPolicy Bypass -File tools\hub\build.ps1

param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here "..\..")).Path
$build = Join-Path $repo ".build"
$dist = Join-Path $build "dist-hub"

Write-Host "[1/4] 检查 PyInstaller..." -ForegroundColor Cyan
& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未安装 PyInstaller，请先执行: $Python -m pip install pyinstaller" -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] 打包中（onedir，内容目录 .hub）..." -ForegroundColor Cyan
Write-Host "[2/4] 生成页面清单 + 收集模块（加模块不用改本脚本）..." -ForegroundColor Cyan
& $Python (Join-Path $here "discover.py") --write
if ($LASTEXITCODE -ne 0) { throw "生成 pages/_manifest.py 失败" }
$mods = & $Python (Join-Path $here "discover.py") --hidden-imports
if ($LASTEXITCODE -ne 0) { throw "枚举 pages/core 模块失败" }

$env:PYINSTALLER_CONFIG_DIR = Join-Path $build "pyinstaller-config"
$hidden = @()
foreach ($m in $mods) {
    $name = $m.Trim()
    if ($name) { $hidden += @("--hidden-import", $name) }
}
$hidden += @(
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

Write-Host "[3/4] 搬到仓库根目录..." -ForegroundColor Cyan
Get-Process hub -ErrorAction SilentlyContinue | Stop-Process -Force
$srcExe = Join-Path $dist "hub\hub.exe"
$srcContent = Join-Path $dist "hub\.hub"
if (-not (Test-Path $srcExe)) { throw "构建产物缺失：$srcExe" }

foreach ($target in @((Join-Path $repo "hub.exe"), (Join-Path $repo ".hub"), (Join-Path $here "app"))) {
    for ($i = 1; $i -le 5; $i++) {
        if (-not (Test-Path $target)) { break }
        try { Remove-Item $target -Recurse -Force -ErrorAction Stop } catch { Start-Sleep -Milliseconds 600 }
    }
    if (Test-Path $target) { throw "无法删除旧产物：$target（先关掉 hub.exe）" }
}
Copy-Item $srcExe $repo -Force
Copy-Item $srcContent (Join-Path $repo ".hub") -Recurse -Force

Write-Host "[4/4] 校验..." -ForegroundColor Cyan
$exe = Join-Path $repo "hub.exe"
$n = (Get-ChildItem (Join-Path $repo ".hub") -Recurse -File | Measure-Object).Count
if (-not (Test-Path $exe) -or $n -lt 900) { throw "产物不完整（$n 个文件）" }
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "构建完成: $exe（+ .hub\ $n 个文件，exe 约 $mb MB）" -ForegroundColor Green