# 建包的範圍驗證判定（PLAYBOOK §D-1a；build_deploy_package.ps1 Step 3 呼叫）。抽成函式才能單獨測（稽核 W4 S1）。
#
# Get-ScopedGateResult：呼叫 `scope_gate.py gate --commit <X> --json`，回傳 @{ Scoped = <判定物件或 $null>; Note = <說明> }。
# 🔴 **fail closed**：只有「exit 0、JSON 讀得懂、accepted 為 true、mode＝scoped、commit 等於 X、base 是 40 位 SHA」全部成立
#    才回 Scoped；其他一切（exit 3、亂碼、例外、commit 不符、直譯器不在）⇒ Scoped＝$null ⇒ 建包照舊跑全量。
# ⚠️ 不對原生程式做 `2>$null`：PS 5.1 在 $ErrorActionPreference=Stop 下，stderr 重導會變成終止錯誤。

function Get-ScopedGateResult {
    param(
        [Parameter(Mandatory = $true)][string]$PyExe,
        [Parameter(Mandatory = $true)][string]$GateScript,
        [Parameter(Mandatory = $true)][string]$Commit
    )
    $out = $null
    $code = $null
    try {
        $out = & $PyExe $GateScript gate --commit $Commit --json
        $code = $LASTEXITCODE
    } catch {
        return @{ Scoped = $null; Note = "範圍驗證判定失敗（$($_.Exception.Message)）⇒ 跑全量" }
    }
    $sg = $null
    try {
        if ($out) { $sg = (@($out) -join "`n") | ConvertFrom-Json }
    } catch {
        return @{ Scoped = $null; Note = "範圍驗證輸出看不懂（exit $code）⇒ 跑全量" }
    }
    if (-not $sg) { return @{ Scoped = $null; Note = "範圍驗證沒有輸出（exit $code）⇒ 跑全量" } }
    if ($code -ne 0 -or $sg.accepted -ne $true) {
        $why = if ($sg.record_present) { "範圍驗證不適用：$($sg.detail)" } else { "" }
        return @{ Scoped = $null; Note = $why }
    }
    if ($sg.mode -ne "scoped") { return @{ Scoped = $null; Note = "範圍驗證回傳的 mode 不是 scoped ⇒ 跑全量" } }
    if ($sg.commit -ne $Commit) {
        return @{ Scoped = $null; Note = "範圍驗證判定的 commit（$($sg.commit)）不是要打包的 $Commit ⇒ 跑全量" }
    }
    if (-not ("$($sg.base)" -match '^[0-9a-f]{40}$')) {
        return @{ Scoped = $null; Note = "範圍驗證沒有完整的基準 SHA ⇒ 跑全量" }
    }
    return @{ Scoped = $sg; Note = "" }
}
