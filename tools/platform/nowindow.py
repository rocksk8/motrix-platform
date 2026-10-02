# -*- coding: utf-8 -*-
"""預設「不跳視窗」：演練（drill_train*）與作者端守門集（author_gate）在背景跑時，不可以讓使用者的畫面一直跳出主控台視窗。

做法：Windows 上把本行程之後所有 `subprocess.Popen`（含 run／check_output／call）預設加上 CREATE_NO_WINDOW 並把 STARTUPINFO 設成 SW_HIDE。
- 呼叫端自己指定了 DETACHED_PROCESS 或 CREATE_NEW_CONSOLE 的，不動（要自己負責；演練起合成安裝伺服器改用 CREATE_NO_WINDOW）。
- 要看視窗除錯：環境變數 MOTRIX_SHOW_WINDOWS=1。
- 只影響**本行程**；子行程再起的行程（例如被測的 apply_update.ps1 內部的 Start-Process）由那支腳本自己負責（它們已用 -WindowStyle Hidden）。
- 非 Windows ⇒ 什麼都不做。
用法：`import nowindow; nowindow.install()`（冪等）。"""
import copy
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
SW_HIDE = 0


def with_hidden(creationflags=0, startupinfo=None, *, nt=None):
    """⇒ (creationflags, startupinfo)：純函式（有題）。nt=None 時看 os.name。"""
    is_nt = (os.name == "nt") if nt is None else nt
    if not is_nt:
        return creationflags, startupinfo
    if not (creationflags & (DETACHED_PROCESS | CREATE_NEW_CONSOLE)):
        creationflags |= CREATE_NO_WINDOW
    startupinfo = subprocess.STARTUPINFO() if startupinfo is None else copy.copy(startupinfo)      # 不改呼叫端的物件
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE
    return creationflags, startupinfo


def install():
    """⇒ True＝已（或本來就）安裝；False＝沒裝（非 Windows 或被 MOTRIX_SHOW_WINDOWS=1 關掉）。"""
    if os.name != "nt" or os.environ.get("MOTRIX_SHOW_WINDOWS") == "1":
        return False
    if getattr(subprocess.Popen, "_motrix_nowindow", False):
        return True
    orig = subprocess.Popen.__init__

    def __init__(self, *args, **kw):
        if len(args) > 12:                         # startupinfo／creationflags 以位置參數傳入：無法安全合併，原樣放行（避免 TypeError: multiple values）
            return orig(self, *args, **kw)
        kw["creationflags"], kw["startupinfo"] = with_hidden(kw.get("creationflags", 0), kw.get("startupinfo"))
        orig(self, *args, **kw)
    subprocess.Popen.__init__ = __init__
    subprocess.Popen._motrix_nowindow = True
    return True
