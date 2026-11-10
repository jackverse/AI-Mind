# 只补建 Gitee Release（代码/tag 已经推上去、只差发行版和附件时用）
#
# Gitee 的 Release 走 HTTP API，必须私人令牌；SSH key 只能推代码，不能建 Release。
# 令牌：https://gitee.com/profile/personal_access_tokens → 新建 → 勾 projects
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\gitee-release.ps1 -Version 0.0.1 -GiteeToken xxxx
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$GiteeToken
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here '..')).Path
$git = 'D:\workplace\Git\bin\git.exe'
if (-not (Test-Path $git)) { $git = 'git' }
$giteeSlug = 'jacktianxz/ai-mind'
$tag = "v$Version"

function Fail($msg) { Write-Host "[gitee] ✗ $msg" -ForegroundColor Red; exit 1 }
function Ok($msg) { Write-Host "[gitee] ✓ $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "[gitee] · $msg" }

$localTag = & $git -C $root tag -l $tag
if (-not $localTag) { Fail "本地没有 tag $tag，先发版再来" }

$verFile = Join-Path $root 'version.json'
$phone = Join-Path $root 'hub-android.apk'
$exe = Join-Path $root 'hub.exe'
foreach ($f in @($verFile, $phone, $exe)) { if (-not (Test-Path $f)) { Fail "缺产物：$f" } }

$vj = Get-Content $verFile -Raw -Encoding UTF8 | ConvertFrom-Json
$zipName = "hub-$tag-win64.zip"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "gitee-release-$tag"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null

$zip = Join-Path $tmp $zipName
$stage = Join-Path $tmp "hub-$tag-win64"
New-Item -ItemType Directory $stage | Out-Null
Copy-Item $exe (Join-Path $stage 'hub.exe')
Copy-Item (Join-Path $root '.hub') (Join-Path $stage '.hub') -Recurse
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
Ok "桌面包 $zipName"

$notes = $vj.notes
$body = @"
## $tag

$notes

**下载（两个地址内容一样）：**
- GitHub：https://github.com/jackverse/AI-Mind/releases/tag/$tag
- Gitee：https://gitee.com/$giteeSlug/releases/tag/$tag

| 产物 | 说明 |
|---|---|
| ``$zipName`` | Windows 桌面端（hub.exe + .hub），解压运行 |
| ``hub-android.apk`` | Android 手机版（v$Version，不带内置数据） |
| ``version.json`` | 版本清单 + sha256，App 自查更新用 |

> 调试签名，仅自装；仓库不含任何个人数据。
"@
$bodyFile = Join-Path $tmp 'body.txt'
[System.IO.File]::WriteAllText($bodyFile, $body, (New-Object System.Text.UTF8Encoding($false)))

# 已经有同 tag 的 release 就复用
$relId = $null
try {
    $list = (& curl.exe -s "https://gitee.com/api/v5/repos/$giteeSlug/releases?access_token=$GiteeToken&per_page=50") | ConvertFrom-Json
    $hit = $list | Where-Object { $_.tag_name -eq $tag } | Select-Object -First 1
    if ($hit) { $relId = $hit.id; Ok "复用已有 Gitee Release（id=$relId）" }
} catch { }

if (-not $relId) {
    $resp = & curl.exe -s -X POST "https://gitee.com/api/v5/repos/$giteeSlug/releases" `
        --data-urlencode "access_token=$GiteeToken" `
        --data-urlencode "tag_name=$tag" `
        --data-urlencode "name=$tag" `
        --data-urlencode "target_commitish=main" `
        --data-urlencode "body@$bodyFile"
    try { $rel = $resp | ConvertFrom-Json } catch { Fail "Gitee 返回不是 JSON：$resp" }
    if (-not $rel.id) { Fail "建 Gitee Release 失败：$resp" }
    $relId = $rel.id
    Ok "Gitee Release：https://gitee.com/$giteeSlug/releases/tag/$tag"
}

$files = @(
    @{ p = $zip; n = $zipName },
    @{ p = $phone; n = 'hub-android.apk' },
    @{ p = $verFile; n = 'version.json' }
)
$existing = @()
try {
    $cur = (& curl.exe -s "https://gitee.com/api/v5/repos/$giteeSlug/releases/$relId?access_token=$GiteeToken") | ConvertFrom-Json
    $existing = @($cur.assets | ForEach-Object { $_.name })
} catch { }

foreach ($f in $files) {
    if ($existing -contains $f.n) { Info "已存在，跳过 $($f.n)"; continue }
    $r = & curl.exe -s -X POST "https://gitee.com/api/v5/repos/$giteeSlug/releases/$relId/attach_files" `
        -F "access_token=$GiteeToken" -F "file=@$($f.p)"
    if ($LASTEXITCODE -ne 0) { Fail "上传 $($f.n) 失败：$r" }
    Info "已上传 $($f.n)"
}

# Gitee 的 attachments 是最终一致的：刚传完查详情可能还是空的，轮询几次再断言
$want = @($files | ForEach-Object { $_.n })
$got = @()
$missing = $want
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 900
    $check = (& curl.exe -s "https://gitee.com/api/v5/repos/$giteeSlug/releases/$relId?access_token=$GiteeToken") | ConvertFrom-Json
    $got = @($check.assets | ForEach-Object { $_.name } | Where-Object { $want -contains $_ })
    $missing = @($want | Where-Object { $got -notcontains $_ })
    if ($missing.Count -eq 0) { break }
}
if ($missing.Count -gt 0) { Fail "Gitee 资产缺失：$($missing -join '、')" }
Ok "Gitee 资产齐全：$($got -join '、')"
Remove-Item $tmp -Recurse -Force
Write-Host "  https://gitee.com/$giteeSlug/releases/tag/$tag"
