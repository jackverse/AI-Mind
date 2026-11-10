# 统一给 tools 下的 .ps1 补 UTF-8 BOM
# 为什么：Windows PowerShell 5.1 不带 BOM 时按 ANSI 读脚本，脚本里的中文会被读成乱码，
# 乱码会吃掉字符串的右引号，直接导致 ParseError。写完脚本 / 用编辑器改过之后跑一次这个。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\sync-bom.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here '..')
$utf8bom = New-Object System.Text.UTF8Encoding($true)
$fixed = 0
Get-ChildItem -Path $root -Recurse -Include *.ps1 -File |
    Where-Object { $_.FullName -notmatch '\\build\\|\\build-watch\\' } |
    ForEach-Object {
        $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
        $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191
        if (-not $hasBom) {
            $text = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
            [System.IO.File]::WriteAllText($_.FullName, $text, $utf8bom)
            Write-Host ("  bom+  " + $_.FullName.Substring($root.Path.Length + 1))
            $fixed++
        }
    }
Write-Host "[bom] 补了 $fixed 个文件"
