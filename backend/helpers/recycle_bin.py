# -*- coding: utf-8 -*-
"""刪除暫存區（資源回收筒）的 L1 契約（第 53 班 P0；設計 docs/platform/plans/RECYCLE-BIN-DESIGN-T52.md、狀態 RECYCLE-BIN-P0-STATE-T53.md）。

[單位] helper:recycle_bin    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] CAP_ADAPTER, CAP_DELETE, RETENTION_DAYS, MAX_SNAPSHOT_BYTES, Adapter, BinError, BinUnavailable, available, adapters, get_adapter, delete, mask_obj
[不變式] 這裡**不認識任何業務表、不碰檔案系統、不讀資料庫**：只定義『擁有模組 ⇄ recyclebin 模組』之間的契約（IP-RB1／IP-RB2，列車定號）。
         擁有模組只 import 本檔（L1）；絕不 import `modules.recyclebin`。recyclebin 模組不在 ⇒ `delete()` 回 None，呼叫端**照舊硬刪並明說**，
         不得靜默（缺席與『進了暫存區』長得不一樣）。
[契約題] backend/modules/recyclebin/tests/、tests/platform/test_recyclebin_guards_t53.py

## 兩個能力（core.registry 的 provider）
- `recyclebin.adapter`（多提供者；擁有模組提供）：名稱＝`entity_type`，值＝回傳 `Adapter` 實例的無參數函式。
  `ModuleSpec.providers[("recyclebin.adapter", "payslip")] = lambda: PayslipBinAdapter()`。
- `recyclebin.delete`（單一提供者；recyclebin 模組提供）：`fn(conn, entity_type, entity_id, user, reason, approved) -> dict`。
  擁有模組的刪除端點把『原本的 DELETE FROM …＋刪檔』換成 `recycle_bin.delete(conn, "payslip", slip_no, user)`（在自己的寫入交易內呼叫）。

## Adapter 要做的事（snapshot／delete_in_tx／restore_in_tx；其餘有預設）
- `can_delete`：**沿用現行刪除規則**（例如只准草稿）——暫存區不放寬任何刪除條件（使用者 D1）。
- `snapshot`：回傳 `{"rows": {表名: [列 dict…]}, "files": [{"root": "uploads", "rel": "<相對路徑>"}…], "label": 顯示名, "parent": (type, id)|None, "meta": {…}}`；
  單據列與所有子表列都要在 rows 裡（還原要用）；檔案只列『這張單據名下、刪除時會被刪掉的』檔。
- `delete_in_tx`：只刪資料列（不刪檔、不 commit）；子表、連結、通知清理照原端點。
- `restore_in_tx`：把 rows 放回去（不 commit）。衝突規則由 adapter 決定並回報：單號已被占用 ⇒ 丟 `BinError('conflict: …')`（recyclebin 把該筆標 restore_failed 並回報原因，
  不覆蓋既有資料）；父層不存在 ⇒ 丟 `BinError('parent_missing: …')`。檔案已由 recyclebin 搬回 `ctx.files`（原路徑→實際路徑）；路徑被占用時實際路徑會不同，adapter 負責改寫列內的路徑欄。
- `impact`：『刪除已核可』入口的影響清單（已付款／已入獎金／已回簽…）；預設空。`can_delete_approved`：預設不支援（P1 各 adapter 實作）。
- `mask`：列表／詳情用的遮罩副本（預設以欄位名稱規則遮罩帳號、身分證、電話、信箱、地址、影像）；還原一律用未遮罩原文。
"""
import re
from typing import Callable, Dict, List, Optional, Tuple

from core import registry

CAP_ADAPTER = "recyclebin.adapter"
CAP_DELETE = "recyclebin.delete"
RETENTION_DAYS = 30                    # 使用者 D4：固定 30 天，不可設定
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024   # 單筆快照上限；超過 ⇒ 拒絕進暫存區（BinError），不悄悄硬刪

#: 預設遮罩的欄位名稱（不分大小寫、駝峰／底線皆可）。看到 → 值換成 MASK；adapter 可覆寫 mask()。
_SENSITIVE = re.compile(
    r"(bank_?account|account_?(number|name)|passbook|id_?number|id_?card|phone|mobile|tel$|email|address|line_?id|password|secret|token|"
    r"signature|image|photo|iban|swift)", re.I)
MASK = "＊＊＊"


class BinError(Exception):
    """暫存區動作不能做（原因字串給人看；前綴 `conflict:`／`parent_missing:`／`too_large:` 為機器可辨識）。"""


class BinUnavailable(BinError):
    """recyclebin 模組不在（未安裝／停用／未授權）。"""


class Adapter:
    """每種單據一個 adapter（擁有模組寫）。子類別至少要實作 snapshot／delete_in_tx／restore_in_tx。"""

    entity_type: str = ""
    label: str = ""                    # 人看的名稱，例：「勞報單」

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        """現行刪除規則（例：只有草稿）。回 (可以, 不行的原因)。"""
        raise NotImplementedError

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        """superadmin 專用『刪除已核可』入口是否支援這種單據／這張單據的狀態。預設不支援。"""
        return False, "此單據類型尚未開放『刪除已核可』"

    def impact(self, conn, entity_id) -> List[dict]:
        """影響清單 `[{kind: 'paid'|'bonus'|'signed_back'|…, label: 人看的說明, blocking: bool}]`。預設空。"""
        return []

    def snapshot(self, conn, entity_id) -> dict:
        raise NotImplementedError

    def delete_in_tx(self, conn, entity_id) -> None:
        raise NotImplementedError

    def restore_in_tx(self, conn, snap: dict, ctx: "RestoreContext") -> dict:
        """回 `{"entity_id": 還原後的主鍵, "renumbered": bool, "notes": [說明…]}`。"""
        raise NotImplementedError

    def cascade_children(self, conn, entity_id) -> List[Tuple[str, str]]:
        """這張單據刪除時連帶刪掉的其他單據 `[(entity_type, entity_id)]`；recyclebin 以同一個 group 一起進暫存區、一起還原。預設無。"""
        return []

    def mask(self, snap: dict) -> dict:
        return mask_obj(snap)


class RestoreContext:
    """還原時交給 adapter 的資訊。`files`＝{(root, 原相對路徑): 實際相對路徑}（檔案已搬回；被占用時實際路徑不同）。"""

    def __init__(self, files: Optional[dict] = None, user: Optional[dict] = None, group: Optional[list] = None):
        self.files = files or {}
        self.user = user or {}
        self.group = group or []

    def file_path(self, root: str, rel: str) -> str:
        return self.files.get((root, rel), rel)


def mask_obj(obj, _key: str = ""):
    """遞迴遮罩：欄位名稱符合 `_SENSITIVE` 的非空值 ⇒ MASK。回新物件，不改原物件。"""
    if isinstance(obj, dict):
        return {k: mask_obj(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_obj(v, _key) for v in obj]
    if _key and _SENSITIVE.search(_key) and obj not in (None, "", 0, False):
        return MASK
    return obj


def available() -> bool:
    """recyclebin 模組是否已載入（擁有模組的刪除端點用它決定『進暫存區』或『照舊硬刪』）。"""
    return registry.single_provider(CAP_DELETE) is not None


def adapters() -> Dict[str, Adapter]:
    """所有已登記的 adapter：{entity_type: Adapter}。擁有模組沒載入 ⇒ 沒有那一項（不是錯誤）。"""
    out = {}
    for name, fn in registry.providers(CAP_ADAPTER).items():
        try:
            a = fn()
        except Exception:                      # noqa: BLE001 — 一個壞掉的 adapter 不拖垮其他類型
            continue
        out[getattr(a, "entity_type", None) or name] = a
    return out


def get_adapter(entity_type: str) -> Optional[Adapter]:
    return adapters().get(entity_type)


def delete(conn, entity_type: str, entity_id, user: dict, reason: str = "", approved: bool = False) -> Optional[dict]:
    """把一張單據（含附件）送進暫存區。**在呼叫端自己的寫入交易內**呼叫；本函式不 commit。
    ⇒ recyclebin 模組不在：回 None（呼叫端照舊硬刪並明說）；在：回 `{"bin_id", "token", "purge_after", "files"}`。
    不能刪（現行規則）⇒ 丟 `BinError`（原因字串）；快照太大 ⇒ `BinError('too_large: …')`。"""
    fn = registry.single_provider(CAP_DELETE)
    if fn is None:
        return None
    return fn(conn, entity_type, entity_id, user, reason, approved)
