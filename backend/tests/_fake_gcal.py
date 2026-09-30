# -*- coding: utf-8 -*-
"""假的 Google 行事曆（2026-09-30 行事曆推送可選）：換掉 L1 `helpers.google_calendar._events_call`，
事件存在記憶體；支援 POST（新建）、PATCH（更新）、DELETE、GET `?privateExtendedProperty=k=v`（合併找回）。
**不連外**：任何測試都不可以打到真的 Google API。

用法：
    cal = install(monkeypatch)                 # 換掉 _events_call
    set_events(monkeypatch, {"case_update": True})   # 事件種類開關（其餘取預設）
    sync_spawn(monkeypatch, some_module)       # 該模組的 spawn_bg_thread 改成同步執行（背景推送在回應前完成）
"""
import itertools
import urllib.parse


class FakeCalendar:
    def __init__(self):
        self.events = {}          # id -> body（含 id）
        self.calls = []           # (method, path, body)
        self._ids = itertools.count(1)

    def __call__(self, method, path="", body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "":
            eid = "fake%d" % next(self._ids)
            self.events[eid] = dict(body or {}, id=eid)
            return {"id": eid}
        if method == "GET" and path.startswith("?"):
            qs = urllib.parse.parse_qs(path[1:])
            k, _, v = (qs.get("privateExtendedProperty") or [""])[0].partition("=")
            items = [e for e in self.events.values()
                     if ((e.get("extendedProperties") or {}).get("private") or {}).get(k) == v]
            return {"items": items}
        eid = urllib.parse.unquote(path.lstrip("/"))
        if method == "PATCH":
            if eid not in self.events:
                raise RuntimeError("Google API 錯誤 404：not found")
            self.events[eid].update(body or {})
            return {"id": eid}
        if method == "DELETE":
            self.events.pop(eid, None)
            return {}
        raise AssertionError("假行事曆不支援：%s %s" % (method, path))

    def methods(self):
        return [m for m, _p, _b in self.calls]


def install(monkeypatch):
    from helpers import google_calendar as gc
    cal = FakeCalendar()
    monkeypatch.setattr(gc, "_events_call", cal)
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)   # 重試等待不真的睡
    return cal


def set_events(monkeypatch=None, events=None, enabled=True):
    """直接寫 system_settings.google_calendar（保留其他欄位）。"""
    from helpers.settings import _get_setting, _set_setting
    cfg = dict(_get_setting("google_calendar", {}) or {})
    cfg["enabled"] = enabled
    if events is not None:
        cfg["events"] = dict(events)
    _set_setting("google_calendar", cfg)


def sync_spawn(monkeypatch, module):
    monkeypatch.setattr(module, "spawn_bg_thread", lambda target, args=(), kwargs=None, **kw: target(*args, **(kwargs or {})))
