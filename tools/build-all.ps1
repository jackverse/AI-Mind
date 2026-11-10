# 一键维护两个产物：hub.exe + 手机 APK（发版只发这两个）
# 用法：powershell -ExecutionPolicy Bypass -File tools\build-all.ps1
#       powershell -ExecutionPolicy Bypass -File tools\build-all.ps1 -Only exe   # exe | android
#
# 公开仓库不带任何个人数据：APK 一律 -SkipSeed（不打内置快照），exe 运行后由用户
# 用自己的 --root / HUB_ROOT 指向数据仓库。
param(
    [switch]$SkipSeed,
    [string]$Only = "",
    # 发版时由 tools\release.ps1 传进来；平时留空就用 build.ps1 里的默认值
    [string]$ApkVersionName = "",
    [int]$ApkVersionCode = 0
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here '..')
$t0 = Get-Date

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  ok  $msg" -ForegroundColor Green }
function Bad($msg) { Write-Host "  ✗   $msg" -ForegroundColor Red }

function Find-Sdk {
    $sdk = $env:ANDROID_HOME
    if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
    if (-not $sdk) { $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    return $sdk
}

$wants = if ($Only) { @($Only) } else { @('exe', 'android') }
$fail = @()

# ---------------------------------------------------------------- exe
if ($wants -contains 'exe') {
    Step '1/2 hub.exe（桌面端）'
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'hub\build.ps1')
    if ($LASTEXITCODE -ne 0) { $fail += 'exe 构建' } else { Ok 'hub.exe 已重建' }
}

# ---------------------------------------------------------------- apk
$apkCommon = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $here 'android-app\build.ps1'))
# 公开仓库永远不带 seed：宁可首屏为空，也不能把个人笔记/账号打进安装包
$apkCommon += '-SkipSeed'
if ($ApkVersionName) { $apkCommon += @('-VersionName', $ApkVersionName) }
if ($ApkVersionCode -gt 0) { $apkCommon += @('-VersionCode', "$ApkVersionCode") }

if ($wants -contains 'android') {
    Step '2/2 手机 APK'
    & powershell @apkCommon
    if ($LASTEXITCODE -ne 0) { $fail += '手机 APK 构建' } else { Ok 'hub-android.apk 已重建' }
}

# ---------------------------------------------------------------- 校验
Step '校验产物'
$exe = Join-Path $repo 'hub.exe'
$phone = Join-Path $repo 'hub-android.apk'
$pkgName = 'com.jackverse.secondbrain'

if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
    $pages = (Get-ChildItem (Join-Path $repo '.hub') -Recurse -File | Measure-Object).Count
    if ($pages -lt 900) { $fail += ".hub 文件数异常（$pages）" }
    & $exe --selftest 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $fail += "hub.exe --selftest 失败（$LASTEXITCODE）" } else { Ok "hub.exe $mb MB · .hub $pages 文件 · 自检通过" }
    Get-Process hub -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $exe } |
        Stop-Process -Force -ErrorAction SilentlyContinue
} else {
    $fail += 'hub.exe 不存在'
}

$sdk = Find-Sdk
$aapt = $null
if ($sdk -and (Test-Path $sdk)) {
    $bt = Get-ChildItem (Join-Path $sdk 'build-tools') -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName 'aapt2.exe') } |
        Sort-Object { [version]($_.Name -replace '-.*$', '') } -Descending |
        Select-Object -First 1
    if ($bt) { $aapt = Join-Path $bt.FullName 'aapt2.exe' }
}

$versions = @{}
if (-not (Test-Path $phone)) { $fail += 'hub-android.apk 不存在' }
else {
    $mb = [math]::Round((Get-Item $phone).Length / 1MB, 2)
    $info = ''
    if ($aapt) {
        $badging = & $aapt dump badging $phone 2>$null
        $pkg = ($badging | Select-String -Pattern "^package:" | Select-Object -First 1).Line
        $label = ($badging | Select-String -Pattern 'application-label:' | Select-Object -First 1).Line
        if ($pkg) {
            $realPkg = [regex]::Match($pkg, "name='([^']*)'").Groups[1].Value
            $ver = [regex]::Match($pkg, "versionName='([^']*)'").Groups[1].Value
            $code = [regex]::Match($pkg, "versionCode='([^']*)'").Groups[1].Value
            $lbl = [regex]::Match($label, "application-label:'([^']*)'").Groups[1].Value
            $info = "$realPkg v$ver($code) · $lbl"
            if ($realPkg -ne $pkgName) { $fail += "APK 包名是 $realPkg，应为 $pkgName" }
            $versions[$realPkg] = [ordered]@{
                versionCode = [int]$code
                versionName = $ver
                apk         = 'hub-android.apk'
                size        = [long](Get-Item $phone).Length
                sha256      = (Get-FileHash $phone -Algorithm SHA256).Hash.ToLower()
            }
        }
    }
    Ok "hub-android.apk $mb MB · $info"
}

# version.json：App 自查更新用（公开仓库只登记手机这一个包名）
$verFile = Join-Path $repo 'version.json'
if ($versions.Count -eq 1) {
    $note = if (Test-Path $verFile) {
        try { (Get-Content $verFile -Raw -Encoding UTF8 | ConvertFrom-Json).notes } catch { '' }
    } else { '' }
    $payload = [ordered]@{ notes = $note }
    foreach ($k in $versions.Keys) { $payload[$k] = $versions[$k] }
    [System.IO.File]::WriteAllText($verFile, ($payload | ConvertTo-Json -Depth 5),
        (New-Object System.Text.UTF8Encoding($false)))
    Ok "version.json 已更新（1 个包名，含 sha256）"
} else {
    $fail += 'version.json 未生成（APK 元信息不全）'
}

$hubPy = Join-Path $here 'hub\hub.py'
$ver = if (Test-Path $hubPy) {
    [regex]::Match((Get-Content $hubPy -Raw -Encoding UTF8), 'VERSION = "([^"]+)"').Groups[1].Value
} else { '' }

$secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
Write-Host ''
if ($fail.Count) {
    Write-Host "[build-all] 失败 $($fail.Count) 项：$($fail -join '、')（$secs s）" -ForegroundColor Red
    exit 1
}
Write-Host "[build-all] 全部通过 · hub $ver · exe + 手机 APK · ${secs}s" -ForegroundColor Green
