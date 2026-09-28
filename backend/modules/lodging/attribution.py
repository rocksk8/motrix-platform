# -*- coding: utf-8 -*-
"""觀光署開放資料的顯名聲明（LODGING-NEARBY §3.6.2，LG-S2）。

政府資料開放授權條款 三(二)（逐字）：「未盡顯名標示義務者，視為自始未取得開放資料之授權。」
⇒ 顯名是授權的**條件**。所有出現官方資料的畫面與輸出（覆蓋層面板、紀錄頁、比較頁、CSV／JSON 匯出、列印）
都從這一支取文字；前端不手寫（頁面經 API 回應的 `attribution` 欄位顯示）。

格式依條款附件：「提供機關／單位 [年份] [開放資料釋出名稱與版本號]　此開放資料依…」；
年份取該批資料的 `dataset_updated_at`（不寫死）；同一畫面有多批 ⇒ 列出各年份。
"""
from modules.lodging.source import DATASET_NAME, DATASET_PROVIDER, DATASET_STANDARD

LICENSE_URL = "https://data.gov.tw/license"
_BODY = ("此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，"
         "使用者於遵守本條款各項規定之前提下，得利用之。")


def years_of(dataset_dates) -> list:
    """資料日期（ISO 字串）→ 排序後不重複的年份；認不得的略過。"""
    ys = set()
    for d in dataset_dates or ():
        if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
            ys.add(d[:4])
    return sorted(ys)


def attribution_text(dataset_dates) -> str:
    """顯名全文。沒有任何可辨識的年份 ⇒ 年份欄寫「年份不明」（仍然顯名，不省略）。"""
    ys = years_of(dataset_dates)
    year = "、".join(ys) if ys else "年份不明"
    return "%s %s %s（%s）　%s　政府資料開放授權條款：%s" % (
        DATASET_PROVIDER, year, DATASET_NAME, DATASET_STANDARD, _BODY, LICENSE_URL)
