# -*- coding: utf-8 -*-
"""permmatrix v2（U0a 組織單位預留）：授權格加可為空的範圍欄位 `scope_json`（NULL＝全部＝今天的行為）。

- 只加欄位、冪等（先看欄位是否存在）；不自己 commit；SQL 寫在這裡（凍住的歷史），不 import 會演進的程式碼。
- 為什麼在這裡而不在 core 的 U0a migration：模組自有的表只能由該模組自己的 migration 補欄（全新安裝時 core 先於 permmatrix 執行，
  那時 perm 表還不存在 ⇒ core 補不到，會造成全新安裝與升級後的庫不同形）。
- 表不存在（v1 沒跑成）⇒ 回原因字串（不記版號、下次再試），不丟例外。
"""

TABLES = ("perm_role_caps", "perm_user_overrides")


def up(conn):
    for t in TABLES:
        cols = {r[1] for r in conn.execute('PRAGMA table_info("%s")' % t).fetchall()}
        if not cols:
            return "%s 表不存在（permmatrix v1 尚未完成），下次再補 scope_json" % t
        if "scope_json" not in cols:
            conn.execute('ALTER TABLE "%s" ADD COLUMN scope_json TEXT' % t)
    return None
