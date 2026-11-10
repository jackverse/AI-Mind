# 打 Android APK（不依赖 Gradle，只用 SDK 自带的 aapt2 / javac / d8 / apksigner）
# 用法：powershell -ExecutionPolicy Bypass -File tools\android-app\build.ps1
#       powershell -ExecutionPolicy Bypass -File tools\android-app\build.ps1 -Watch   # OPPO Watch 版
# 发版别直接调这个：走 tools\release.ps1，它会自动递增 versionCode（覆盖同名 release 会让 APK 收不到更新）
param(
    [string]$Out = "",
    [switch]$SkipSeed,
    [switch]$Watch,
    [switch]$Debuggable,          # 仅本机调试：打出来的包带 android:debuggable，可用 run-as 看/写私有数据
    [string]$VersionName = "0.0.1",
    [int]$VersionCode = 1
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here '..\..')
$build = Join-Path $here 'build'
if ($Watch) { $build = Join-Path $here 'build-watch' }

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
if ($Watch) {
    $webSrc = Join-Path $repo 'tools\watch-app\web'
} else {
    $webSrc = Join-Path $repo 'tools\hub-web\web'
}
$webDst = Join-Path $build 'assets\web'
New-Item -ItemType Directory -Path $webDst -Force | Out-Null
Get-ChildItem $webSrc -Recurse -File | Where-Object {
    $_.FullName -notlike '*\web\data\*' -and $_.Name -ne '__test.html'
} | ForEach-Object {
    $rel = $_.FullName.Substring($webSrc.Length + 1)
    $dst = Join-Path $webDst $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
    Copy-Item $_.FullName $dst -Force
}
if ($Watch) {
    # 手表版复用网页版的 bundle 计算（把本地文件算成同一份 bundle），不复制整套 UI
    Copy-Item (Join-Path $repo 'tools\hub-web\web\android-bundle.js') (Join-Path $webDst 'android-bundle.js') -Force
}
$variant = if ($Watch) { "watch" } else { "phone" }
Ok "web 资源已复制（$variant）"

# ---------------------------------------------------------------- assets：seed
if (-not $SkipSeed) {
    $seed = Join-Path $build 'assets\seed'
    $notesSrc = Join-Path $repo 'notes'
    Get-ChildItem $notesSrc -Recurse -File | Where-Object {
        $_.Extension -in '.md', '.json', '.jsonl'
    } | ForEach-Object {
        $rel = $_.FullName.Substring($notesSrc.Length + 1)
        $dst = Join-Path (Join-Path $seed 'notes') $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item $_.FullName $dst -Force
    }
    $hubSrc = Join-Path $repo 'data\hub'
    Get-ChildItem $hubSrc -Recurse -File -Filter *.json | Where-Object {
        $_.Name -notlike 'auth.*' -and
        $_.Name -notin @('sync.json', 'mail.json') -and
        $_.Name -notlike 'usage*' -and
        $_.FullName -notlike '*\exports\*'
    } | ForEach-Object {
        $rel = $_.FullName.Substring($hubSrc.Length + 1)
        $dst = Join-Path (Join-Path $seed 'data\hub') $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item $_.FullName $dst -Force
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
    Ok "内置快照已打包（$seedSize MB）"
}

# ---------------------------------------------------------------- 资源 + Manifest
Write-Host '→ aapt2 compile'
& (Join-Path $btPath 'aapt2.exe') compile --dir (Join-Path $here 'app\res') -o $build\res.zip
if ($LASTEXITCODE -ne 0) { Fail "aapt2 compile 失败" }

Write-Host '→ aapt2 link'
$manifest = if ($Watch) {
    Join-Path $here 'app\AndroidManifest-watch.xml'
} else {
    Join-Path $here 'app\AndroidManifest.xml'
}

# 清单自检：源码里每个 Activity 都必须在清单里声明，漏一个就会在点进去时
# ActivityNotFoundException 直接闪退（v1.20.0/1.20.1 的「登录新账号」就这么挂的）
$manifestText = Get-Content $manifest -Raw -Encoding UTF8
# 注释里也会出现类名，先剔掉，免得注释把漏声明的 Activity「掩盖」过去
$manifestText = [regex]::Replace($manifestText, '(?s)<!--.*?-->', '')
$missing = @()
Get-ChildItem (Join-Path $here 'app\src') -Recurse -Filter *.java | ForEach-Object {
    $text = Get-Content $_.FullName -Raw -Encoding UTF8
    if ($text -match 'class\s+(\w+)\s+extends\s+(android\.app\.)?Activity\b') {
        $cls = $Matches[1]
        if ($cls -ne 'MainActivity' -and $manifestText -notmatch [regex]::Escape($cls)) {
            $missing += $cls
        }
    }
}
if ($missing.Count -gt 0) {
    Fail "清单里没声明这些 Activity：$($missing -join '、')（运行时会闪退）——检查 $(Split-Path -Leaf $manifest)"
}
Ok "清单里的 Activity 声明齐全（$((Get-ChildItem (Join-Path $here 'app\src') -Recurse -Filter *.java | Measure-Object).Count) 个源文件已查）"

$aaptArgs = @(
    'link', '-o', (Join-Path $build 'app-unsigned.apk'),
    '-I', $androidJar,
    '--manifest', $manifest,
    '-A', (Join-Path $build 'assets'),
    '--java', (Join-Path $build 'gen'),
    '--min-sdk-version', '26', '--target-sdk-version', '34',
    '--version-code', "$VersionCode", '--version-name', $VersionName
)
# 调试包才加 --debug-mode：给 aapt2 带上 android:debuggable，run-as 才能看私有数据；正常包不带
if ($Debuggable) { $aaptArgs += '--debug-mode' }
$aaptArgs += (Join-Path $build 'res.zip')
& (Join-Path $btPath 'aapt2.exe') @aaptArgs
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
$outApk = if ($Out) { $Out }
          elseif ($Watch) { Join-Path $repo 'hub-watch.apk' }
          else { Join-Path $repo 'hub-android.apk' }
Write-Host '→ apksigner'
& (Join-Path $btPath 'apksigner.bat') sign --ks $ks --ks-pass pass:android --key-pass pass:android `
    --v4-signing-enabled false --out $outApk $build\app-aligned.apk
if ($LASTEXITCODE -ne 0) { Fail "apksigner 失败" }
& (Join-Path $btPath 'apksigner.bat') verify --print-certs $outApk | Select-Object -First 2

$size = [math]::Round(((Get-Item $outApk).Length / 1MB), 2)
Ok "APK: $outApk（$size MB）"
