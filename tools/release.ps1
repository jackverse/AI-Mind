# 一次发版：递增版本 → 重建 exe + 手机 APK（无 seed）→ 打 tag → 同时推 GitHub / Gitee
# → 两个仓库各建 Release，上传 hub-vX-win64.zip + hub-android.apk + version.json
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\release.ps1 -Version 0.0.2 -Notes "改了什么"
#   powershell -ExecutionPolicy Bypass -File tools\release.ps1 -Version 0.0.2 -GiteeToken xxxx
#
# 版本从 0.0.1 起慢慢加；versionCode 只增不减，禁止覆盖同名 tag（覆盖了 App 就收不到更新）。
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = "",
    [int]$VersionCode = 0,
    [switch]$SkipBuild,
    [switch]$Force,                 # 只在第一次重置历史时用：强推 main
    [string]$GiteeToken = $env:GITEE_TOKEN
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here '..')).Path
$git = 'D:\workplace\Git\bin\git.exe'
if (-not (Test-Path $git)) { $git = 'git' }
$repoSlug = 'jackverse/AI-Mind'
$giteeSlug = 'jacktianxz/ai-mind'

function Fail($msg) { Write-Host "[release] ✗ $msg" -ForegroundColor Red; exit 1 }
function Ok($msg) { Write-Host "[release] ✓ $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "[release] · $msg" }

function Invoke-Git {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $git -C $root @args 2>&1 | Out-Null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "版本号要写成 x.y.z，收到：$Version" }
$tag = "v$Version"

# ---------------------------------------------------------------- 1. 版本递增
$verFile = Join-Path $root 'version.json'
$oldCodes = @()
if (Test-Path $verFile) {
    $old = Get-Content $verFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $old.PSObject.Properties) {
        if ($p.Name -ne 'notes' -and $p.Value.versionCode) { $oldCodes += [int]$p.Value.versionCode }
    }
}
$maxOld = if ($oldCodes.Count) { ($oldCodes | Measure-Object -Maximum).Maximum } else { 0 }
if ($VersionCode -le 0) { $VersionCode = $maxOld + 1 }
if ($VersionCode -le $maxOld) { Fail "versionCode 必须大于现有 $maxOld，收到 $VersionCode" }
Info "版本 $tag · versionCode $VersionCode（上一个 $maxOld）"

$localTag = & $git -C $root tag -l $tag
if ($localTag) { Fail "本地已有 tag $tag，禁止覆盖" }
if (-not $SkipBuild -and -not $Force) {
    $remoteTag = & $git -C $root ls-remote --tags origin "refs/tags/$tag" 2>$null
    if ($remoteTag) { Fail "GitHub 已有 tag $tag，禁止覆盖" }
}

# ---------------------------------------------------------------- 2. 改版本号
$hubPy = Join-Path $here 'hub\hub.py'
$py = Get-Content $hubPy -Raw -Encoding UTF8
$py = [regex]::Replace($py, 'VERSION = "[^"]+"', "VERSION = `"$Version`"")
[System.IO.File]::WriteAllText($hubPy, $py, (New-Object System.Text.UTF8Encoding($false)))
Ok "hub.py VERSION → $Version"

if ($Notes) {
    $json = if (Test-Path $verFile) { Get-Content $verFile -Raw -Encoding UTF8 | ConvertFrom-Json } else { [pscustomobject]@{} }
    $json | Add-Member -NotePropertyName notes -NotePropertyValue $Notes -Force
    [System.IO.File]::WriteAllText($verFile, ($json | ConvertTo-Json -Depth 5),
        (New-Object System.Text.UTF8Encoding($false)))
    Ok 'version.json notes 已写入'
}

# ---------------------------------------------------------------- 3. 构建
if (-not $SkipBuild) {
    Info '重建 exe + 手机 APK（不带 seed）…'
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'build-all.ps1') `
        -ApkVersionName $Version -ApkVersionCode $VersionCode
    if ($LASTEXITCODE -ne 0) { Fail 'build-all 失败' }
    Ok '两个产物构建 + 校验通过'
} else {
    Info '跳过构建（-SkipBuild）'
}

$exe = Join-Path $root 'hub.exe'
$phone = Join-Path $root 'hub-android.apk'
foreach ($f in @($exe, $phone, $verFile)) {
    if (-not (Test-Path $f)) { Fail "缺产物：$f" }
}

$vj = Get-Content $verFile -Raw -Encoding UTF8 | ConvertFrom-Json
$p = $vj.PSObject.Properties | Where-Object { $_.Name -ne 'notes' } | Select-Object -First 1
if (-not $p) { Fail 'version.json 里没有包条目' }
$real = (Get-FileHash $phone -Algorithm SHA256).Hash.ToLower()
if ($real -ne $p.Value.sha256.ToLower()) { Fail 'APK 的 sha256 与 version.json 不一致' }
if ($p.Value.versionCode -ne $VersionCode -or $p.Value.versionName -ne $Version) { Fail 'version.json 版本号不对' }
Ok "version.json 自洽（$($p.Name) · code $VersionCode · sha256 对）"

# ---------------------------------------------------------------- 4. 桌面包
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "aimind-release-$tag"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
$stage = Join-Path $tmp "hub-$tag-win64"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item $exe (Join-Path $stage 'hub.exe')
Copy-Item (Join-Path $root '.hub') (Join-Path $stage '.hub') -Recurse
$zipName = "hub-$tag-win64.zip"
$zip = Join-Path $tmp $zipName
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
$zipMb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Ok "桌面包 $zipName $zipMb MB"

# ---------------------------------------------------------------- 5. 提交 + tag
& $git -C $root add -A
& $git -C $root commit -m "release: $tag（exe + 手机 APK，versionCode $VersionCode）" | Out-Null
if ($LASTEXITCODE -ne 0) { Info '没有可提交的改动（可能 -SkipBuild），继续打 tag' }
& $git -C $root tag -a $tag -m "release $tag"
Ok "已提交并打 tag $tag"

# ---------------------------------------------------------------- 6. 推送两个仓库
$branch = 'main'
if ($Force) {
    if ((Invoke-Git 'push' '-f' 'origin' "HEAD:$branch") -ne 0) { Fail 'GitHub 强推失败' }
} else {
    if ((Invoke-Git 'push' 'origin' "HEAD:$branch") -ne 0) {
        Info 'GitHub 推送被拒，先 rebase…'
        [void](Invoke-Git 'fetch' 'origin')
        if ((Invoke-Git 'rebase' "origin/$branch") -ne 0) { Fail 'rebase 有冲突' }
        [void](Invoke-Git 'tag' '-f' '-a' $tag '-m' "release $tag")
        if ((Invoke-Git 'push' 'origin' "HEAD:$branch") -ne 0) { Fail 'GitHub 推送失败' }
    }
}
if ((Invoke-Git 'push' 'origin' $tag) -ne 0) { Fail 'GitHub tag 推送失败' }
Ok 'GitHub 已推送'

if ((Invoke-Git 'push' 'gitee' "HEAD:$branch") -ne 0) {
    if ($Force) {
        if ((Invoke-Git 'push' '-f' 'gitee' "HEAD:$branch") -ne 0) { Fail 'Gitee 推送失败' }
    } else { Fail 'Gitee 推送失败（检查 SSH 权限）' }
}
if ((Invoke-Git 'push' '-f' 'gitee' $tag) -ne 0) { Fail 'Gitee tag 推送失败' }
Ok 'Gitee 已推送'

# ---------------------------------------------------------------- 7. GitHub Release
$cred = "protocol=https`nhost=github.com`n`n" | & $git credential fill 2>$null
$token = (($cred | Where-Object { $_ -like 'password=*' }) -replace '^password=','')
if (-not $token) { Fail '取不到 GitHub 凭据' }
$h = @{ Authorization = "token $token"; 'User-Agent' = 'dsh-release'; Accept = 'application/vnd.github+json' }

$releaseNotes = if ($Notes) { $Notes } else { $vj.notes }
$body = @"
## $tag

$releaseNotes

**下载（两个地址内容一样）：**
- GitHub：https://github.com/$repoSlug/releases/tag/$tag
- Gitee：https://gitee.com/$giteeSlug/releases/tag/$tag

| 产物 | 说明 |
|---|---|
| ``$zipName`` | Windows 桌面端（hub.exe + .hub），解压运行 |
| ``hub-android.apk`` | Android 手机版（v$Version / code $VersionCode，不带内置数据） |
| ``version.json`` | 版本清单 + sha256，App 自查更新用 |

> 调试签名，仅自装；仓库不含任何个人数据。
"@

$payload = @{ tag_name = $tag; name = "$tag"; body = $body; draft = $false; prerelease = $false } |
    ConvertTo-Json -Depth 5
try {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repoSlug/releases" -Method Post `
        -Headers $h -ContentType 'application/json; charset=utf-8' `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
} catch { Fail "建 GitHub Release 失败：$($_.Exception.Message)" }
Ok "GitHub Release：$($rel.html_url)"

$upload = "https://uploads.github.com/repos/$repoSlug/releases/$($rel.id)/assets"
$files = @(
    @{ p = $zip; n = $zipName; t = 'application/zip' },
    @{ p = $phone; n = 'hub-android.apk'; t = 'application/vnd.android.package-archive' },
    @{ p = $verFile; n = 'version.json'; t = 'application/json' }
)
foreach ($f in $files) {
    Invoke-RestMethod -Uri ($upload + '?name=' + $f.n) -Method Post -Headers $h `
        -ContentType $f.t -InFile $f.p | Out-Null
    Info "GitHub 已上传 $($f.n)"
}

# ---------------------------------------------------------------- 8. Gitee Release
if (-not $GiteeToken) {
    Write-Host '[release] ! 没有 Gitee token，代码和 tag 已推上去，Release 没建。' -ForegroundColor Yellow
    Write-Host '          到 https://gitee.com/profile/personal_access_tokens 建一个（勾 projects），' -ForegroundColor Yellow
    Write-Host '          再跑：tools\release.ps1 -Version <同版本> -SkipBuild -GiteeToken <token>' -ForegroundColor Yellow
} else {
    $bodyFile = Join-Path $tmp 'gitee-body.txt'
    [System.IO.File]::WriteAllText($bodyFile, $body, (New-Object System.Text.UTF8Encoding($false)))
    $resp = & curl.exe -s -X POST "https://gitee.com/api/v5/repos/$giteeSlug/releases" `
        --data-urlencode "access_token=$GiteeToken" `
        --data-urlencode "tag_name=$tag" `
        --data-urlencode "name=$tag" `
        --data-urlencode "target_commitish=main" `
        --data-urlencode "body@$bodyFile"
    try { $grel = $resp | ConvertFrom-Json } catch { Fail "Gitee 返回不是 JSON：$resp" }
    if (-not $grel.id) { Fail "建 Gitee Release 失败：$resp" }
    Ok "Gitee Release：$($grel.html_url)"

    foreach ($f in $files) {
        $r = & curl.exe -s -X POST "https://gitee.com/api/v5/repos/$giteeSlug/releases/$($grel.id)/attach_files" `
            -F "access_token=$GiteeToken" -F "file=@$($f.p)"
        if ($LASTEXITCODE -ne 0) { Fail "Gitee 上传 $($f.n) 失败" }
        Info "Gitee 已上传 $($f.n)"
    }
    $check = Invoke-RestMethod -Uri "https://gitee.com/api/v5/repos/$giteeSlug/releases/$($grel.id)?access_token=$GiteeToken"
    $got = @($check.assets | ForEach-Object { $_.name })
    foreach ($f in $files) { if ($got -notcontains $f.n) { Fail "Gitee 资产缺失：$($f.n)" } }
    Ok 'Gitee 资产齐全'
}

Remove-Item $tmp -Recurse -Force
Ok "完成 · $tag · code $VersionCode"
Write-Host "  GitHub：https://github.com/$repoSlug/releases/tag/$tag"
Write-Host "  Gitee ：https://gitee.com/$giteeSlug/releases/tag/$tag"
