"""「需要某個 L2 模組才能跑」的題怎麼標（M01-PLAN §5 ④，稽核 D M4-M3，主持裁示）。

行為與 `core.source_tree.module_installed` 略過相同（看 `modules/<key>/module.json`，不看資料夾）。

- 整檔都需要：檔頭 `pytestmark = requires_module("case", "理由")`
- 檔案在模組層就 import 了該模組（沒有模組時連收集都會失敗）：在那行 import 之前加 `skip_module_unless("case", "理由")`
- 只有幾題需要：那幾題加 `@requires_module("case", "理由")`

⚠ 驗「L1／其他模組在該模組不在時照常」的題**不可以**標，要改成驗不在時的行為（主持裁示）。
"""
import pytest

from core import source_tree


def _installed(key):
    return source_tree.module_installed("modules/%s/" % key)


def requires_module(key, reason):
    return pytest.mark.skipif(not _installed(key), reason="需要模組 %s：%s" % (key, reason))


def skip_module_unless(key, reason):
    """模組不在 ⇒ 整檔略過（在模組層 import 該模組之前呼叫）。"""
    if not _installed(key):
        pytest.skip("需要模組 %s：%s" % (key, reason), allow_module_level=True)
