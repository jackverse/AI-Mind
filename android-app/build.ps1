# 打 Android APK（不依赖 Gradle，只用 SDK 自带的 aapt2 / javac / d8 / apksigner）
# 用法：
#   powershell -ExecutionPolicy Bypass -File android-app\build.ps1
#   powershell -ExecutionPolicy Bypass -File android-app\build.ps1 -VaultRoot D:\path\to\vault
# 说明：默认不内置任何数据（APK 首启为空）；-VaultRoot 只在本机把数据打进 seed.zip，产物不进仓库。
param(
    [string]$Out = "",
    [string]$VaultRoot = "",
    [switch]$SkipSeed
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$build = Join-Path $here 'build'
$dist = Join-Path $repo 'dist'

function Fail($msg) { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }
function Ok($msg) { Write-Host "✓ $msg" -ForegroundColor Green }

# ---------------------------------------------------------------- 环境
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) { $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path $sdk)) { Fail "找不到 Android SDK，请设置 ANDROID_HOME" }

$bt = Get-ChildItem (Join-Path $sdk 'build-tools') -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'aapt2.exe') } |
    Sort-Object { [version]($_.Name -replace '-.*$','') } -Descending |
    Select-Object -First 1
if (-not $bt) { Fail "build-tools 里没有 aapt2" }
$btPath = $bt.FullName

$platform = Get-ChildItem (Join-Path $sdk 'platforms') -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'android.jar') } |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $platform) { Fail "platforms 里没有 android.jar" }
$androidJar = Join-Path $platform.FullName 'android.jar'

$jdk = $env:JAVA_HOME
if (-not $jdk) { $jdk = (Get-Command javac -ErrorAction SilentlyContinue).Source | Split-Path -Parent | Split-Path -Parent }
$javac = Join-Path $jdk 'bin\javac.exe'
$jarTool = Join-Path $jdk 'bin\jar.exe'
$keytool = Join-Path $jdk 'bin\keytool.exe'
if (-not (Test-Path $javac)) { Fail "找不到 javac（JAVA_HOME=$jdk）" }

Write-Host "SDK: $sdk"
Write-Host "build-tools: $($bt.Name) · platform: $($platform.Name)"

# ---------------------------------------------------------------- 清理
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Path $build\assets, $build\gen, $build\classes, $build\dex, $build\res | Out-Null

# ---------------------------------------------------------------- assets：web
$webSrc = Join-Path $repo 'hub-web\web'
$webDst = Join-Path $build 'assets\web'
if (-not (Test-Path $webSrc)) { Fail "找不到 hub-web\web" }
New-Item -ItemType Directory -Path $webDst -Force | Out-Null
Get-ChildItem $webSrc -Recurse -File | Where-Object {
    $_.FullName -notlike '*\web\data\*' -and $_.Name -ne '__test.html'
} | ForEach-Object {
    $rel = $_.FullName.Substring($webSrc.Length + 1)
    $dst = Join-Path $webDst $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
    Copy-Item $_.FullName $dst -Force
}
Ok "web 资源已复制"

# ---------------------------------------------------------------- assets：seed（可选）
if (-not $SkipSeed -and $VaultRoot) {
    if (-not (Test-Path $VaultRoot)) { Fail "VaultRoot 不存在：$VaultRoot" }
    $vault = (Resolve-Path $VaultRoot).Path
    $hubSrc = Join-Path $vault 'data\hub'
    if (-not (Test-Path $hubSrc)) { Fail "VaultRoot 下没有 data\hub\：$vault" }
    $seed = Join-Path $build 'assets\seed'
    New-Item -ItemType Directory -Path $seed -Force | Out-Null
    foreach ($kind in @('douyin', 'xhs')) {
        $src = Join-Path $hubSrc $kind
        if (-not (Test-Path $src)) { continue }
        Get-ChildItem $src -Recurse -File -Filter *.json | Where-Object {
            $_.Name -notlike 'auth.*' -and
            $_.Name -notin @('sync.json', 'mail.json') -and
            $_.Name -notlike 'usage*' -and
            $_.FullName -notlike '*\exports\*' -and
            $_.FullName -notlike '*\probe\*'
        } | ForEach-Object {
            $rel = $_.FullName.Substring($hubSrc.Length + 1)
            $dst = Join-Path (Join-Path $seed 'data\hub') $rel
            New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
            Copy-Item $_.FullName $dst -Force
        }
    }
    $seedSize = [math]::Round(((Get-ChildItem $seed -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 2)
    # aapt2 对中文文件名不友好，打包成一个 zip，App 首次启动自己解压
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $seedZip = Join-Path $build 'assets\seed.zip'
    $zip = [System.IO.Compression.ZipFile]::Open($seedZip, 'Create')
    try {
        Get-ChildItem $seed -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($seed.Length + 1).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $_.FullName, $rel, 'Optimal') | Out-Null
        }
    } finally { $zip.Dispose() }
    Remove-Item $seed -Recurse -Force
    Ok "内置快照已打包（$seedSize MB，仅本机 APK）"
} elseif (-not $SkipSeed) {
    Write-Host '未指定 -VaultRoot，不内置快照：APK 首启为空，同步后才有数据。' -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 资源 + Manifest
Write-Host '→ aapt2 compile'
& (Join-Path $btPath 'aapt2.exe') compile --dir (Join-Path $here 'app\res') -o $build\res.zip
if ($LASTEXITCODE -ne 0) { Fail "aapt2 compile 失败" }

Write-Host '→ aapt2 link'
& (Join-Path $btPath 'aapt2.exe') link -o $build\app-unsigned.apk `
    -I $androidJar `
    --manifest (Join-Path $here 'app\AndroidManifest.xml') `
    -A $build\assets `
    --java $build\gen `
    --min-sdk-version 26 --target-sdk-version 34 `
    --version-code 1 --version-name 1.0 `
    $build\res.zip
if ($LASTEXITCODE -ne 0) { Fail "aapt2 link 失败" }
Ok "资源与清单已打包"

# ---------------------------------------------------------------- 编译 Java
Write-Host '→ javac'
$sources = @()
Get-ChildItem (Join-Path $here 'app\src') -Recurse -Filter *.java | ForEach-Object { $sources += $_.FullName }
Get-ChildItem $build\gen -Recurse -Filter *.java | ForEach-Object { $sources += $_.FullName }
& $javac -encoding UTF-8 -source 1.8 -target 1.8 -Xlint:-options -classpath $androidJar -d $build\classes $sources
if ($LASTEXITCODE -ne 0) { Fail "javac 编译失败" }
Ok "Java 编译完成"

# ---------------------------------------------------------------- dex
Write-Host '→ d8'
& $jarTool cf (Join-Path $build 'classes.jar') -C (Join-Path $build 'classes') .
& (Join-Path $btPath 'd8.bat') --lib $androidJar --min-api 26 --output (Join-Path $build 'dex') (Join-Path $build 'classes.jar')
if ($LASTEXITCODE -ne 0) { Fail "d8 失败" }
Ok "dex 生成完成"

# ---------------------------------------------------------------- 合并进 APK
Write-Host '→ 写入 classes.dex'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open((Join-Path $build 'app-unsigned.apk'), 'Update')
try {
    if ($zip.GetEntry('classes.dex')) { $zip.GetEntry('classes.dex').Delete() }
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip, (Join-Path $build 'dex\classes.dex'), 'classes.dex', 'Optimal') | Out-Null
} finally { $zip.Dispose() }

# ---------------------------------------------------------------- 对齐 + 签名
Write-Host '→ zipalign'
& (Join-Path $btPath 'zipalign.exe') -p -f 4 (Join-Path $build 'app-unsigned.apk') (Join-Path $build 'app-aligned.apk')
if ($LASTEXITCODE -ne 0) { Fail "zipalign 失败" }

$ks = Join-Path $here 'debug.keystore'
if (-not (Test-Path $ks)) {
    Write-Host '→ 生成调试签名证书'
    & $keytool -genkeypair -keystore $ks -storepass android -alias androiddebugkey `
        -keypass android -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US" | Out-Null
}
if (-not $Out) {
    $Out = Join-Path $dist 'hub-android.apk'
}
$outDir = Split-Path -Parent $Out
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
Write-Host '→ apksigner'
& (Join-Path $btPath 'apksigner.bat') sign --ks $ks --ks-pass pass:android --key-pass pass:android `
    --v4-signing-enabled false --out $Out $build\app-aligned.apk
if ($LASTEXITCODE -ne 0) { Fail "apksigner 失败" }
& (Join-Path $btPath 'apksigner.bat') verify --print-certs $Out | Select-Object -First 2

$size = [math]::Round(((Get-Item $Out).Length / 1MB), 2)
Ok "APK: $Out（$size MB）"
