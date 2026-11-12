# -*- coding: utf-8 -*-
"""T85 設定群組：匯入精靈（import_wizard）。

[單位] helper:settings_groups_import_wizard    [層] L1    [穩定度] 實驗
[公開介面] （無）
[不變式] `enabled` 預設 0＝匯入精靈不開放（頁面與範本／解析端點都回「尚未開放」）；客戶頁、料號頁原有的 Excel 匯入按鈕**不受這個開關影響**。
    精靈本身不寫資料：客戶／料號走既有的 `/api/customers/import-rows`、`/api/parts/import-rows`（預覽→確認），員工走 `/api/users/import-rows`（只有最高管理者）。
    `max_file_mb`＝上傳檔案大小上限（1～20 MB，預設 5）；列數上限與欄位上限寫在 modules/importer/parser.py。
[契約題] modules/importer/tests/test_importer_t85.py
"""


def _register(S, _register_core):
    _register_core(
        "import_wizard", "匯入精靈",
        [
            S("enabled", "int", 0, min=0, max=1, risk="none", recommended=0,
              question="要開放「匯入精靈」嗎？", label="開放匯入精靈",
              help="匯入精靈可下載範本、上傳填好的 Excel 檔、先預覽再確認，把既有的客戶、料號、員工資料搬進系統。客戶與料號的匯入權限同原本的匯入；員工匯入只有最高管理者。",
              impact="只決定匯入精靈頁面與入口是否開放；客戶頁、料號頁原有的匯入按鈕不受影響。開啟與關閉立即生效，不會動到任何已存在的資料。",
              choices=[(0, "關閉（預設）", "沒有匯入精靈入口。"), (1, "開啟", "客戶頁、料號頁會出現「或用匯入精靈」的連結。")]),
            S("max_file_mb", "int", 5, min=1, max=20, unit="MB", risk="none", recommended=5,
              question="匯入檔案最大可以多大？", label="匯入檔案大小上限（MB）",
              help="超過上限的檔案在解析前就會被拒絕，並提示拆檔。",
              impact="只影響匯入精靈的上傳大小；不影響其他上傳功能。"),
        ],
        sensitive=False, risk="none",
        help="匯入精靈的開關與上傳大小上限；預設關閉。",
    )
