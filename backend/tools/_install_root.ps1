# _install_root.ps1 — 「這是哪個安裝目錄、能不能在這裡套用更新」的判定（去識別化 sale 包用；docs/platform/PRODROOT-GUARD-DESIGN.md）
#
# 自用（own）包的部署腳本在開頭寫死安裝目錄與 port，並比對「腳本所在位置＝寫死的路徑」——那是安全守門，防止在開發樹上套用更新。
# sale 包不能帶著本公司的路徑，所以建包時把那兩段換成呼叫本檔：安裝目錄由腳本所在位置推得（<根>\backend\tools\ 往上兩層），
# 守門改成下面這幾條「同樣會擋開發樹」的條件（不用路徑字串判斷——帳號名、資料夾名都不看）：
#   ① 根下有 backend\.install_identity（被確認過的安裝；首次啟動即建立）
#   ② 根與 backend 下沒有 .git
#   ③ 根下沒有開發／演練標記 .no_email_send、.no_cloud_archive
#   ④ backend\.install_port（若有）是 1～65535 的整數；沒有 ⇒ 666
# 回傳 @{ Root; Port; Error }：Error 非空 ⇒ 呼叫端必須中止（Root 仍會給值，讓中止前的程式不因 null 當掉）。
# 本檔自用包也帶著（無害）；own 的腳本不呼叫它。

function Test-InstallRoot {
    param([string]$Root)
    $err = $null
    $port = 666
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return @{ Root = $Root; Port = $port; Error = "安裝目錄不存在：$Root" }
    }
    $backend = Join-Path $Root "backend"
    if (-not (Test-Path -LiteralPath (Join-Path $backend ".install_identity") -PathType Leaf)) {
        $err = "根目錄下沒有 backend\.install_identity——這不是一個啟動過、被確認過的安裝（開發樹或還沒啟動過的目錄不可套用更新）"
    }
    elseif ((Test-Path -LiteralPath (Join-Path $Root ".git")) -or (Test-Path -LiteralPath (Join-Path $backend ".git"))) {
        $err = "安裝目錄裡有 .git——這是開發樹，不可套用更新"
    }
    else {
        foreach ($marker in @(".no_email_send", ".no_cloud_archive")) {
            if (Test-Path -LiteralPath (Join-Path $Root $marker)) {
                $err = "安裝目錄裡有開發／演練標記 $marker——不可套用更新"
                break
            }
        }
    }
    $portFile = Join-Path $backend ".install_port"
    if (Test-Path -LiteralPath $portFile -PathType Leaf) {
        $txt = ((Get-Content -LiteralPath $portFile -Raw -ErrorAction SilentlyContinue) + "").Trim()
        $n = 0
        if ($txt -match '^\d{1,5}$' -and [int]::TryParse($txt, [ref]$n) -and $n -ge 1 -and $n -le 65535) {
            $port = $n
        }
        elseif (-not $err) {
            $err = "backend\.install_port 的內容不是 1～65535 的整數"
        }
    }
    return @{ Root = $Root; Port = $port; Error = $err }
}

function Resolve-InstallRoot {
    # $ScriptDir ＝ <根>\backend\tools（部署腳本所在的資料夾，通常傳 $PSScriptRoot）
    param([string]$ScriptDir)
    $root = (Get-Item -LiteralPath $ScriptDir).Parent.Parent.FullName
    return (Test-InstallRoot -Root $root)
}
