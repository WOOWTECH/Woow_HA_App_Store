#!/usr/bin/env python3
"""HA layer: the "{agent} is not signed in" hint points at the add-on's CLI Terminal.

The core image's white-label patch (paas-odoo-ci open-design/woow-patches/white-label-links.py) rewrites
this run-error text for the WOOW PaaS: open the terminal at "<service URL>/console/" or enter an API key in
the WoowTech platform's service settings. Neither exists in Home Assistant. Here the terminal is the
add-on's **CLI Terminal** button (injected by ha-ingress.js, bottom right of the OpenDesign page) and API
keys are OpenDesign's own browser-local Settings.

Every edit is an exact-text replacement of one i18n entry in the built web chunks and must match exactly
once across all chunks; otherwise the build FAILS (a core change must re-check this patch, never ship the
PaaS wording silently). Source maps are left alone (not executed).

  sign-in-hint.py <web out dir>
"""
import os
import sys

KEY = '"chat.runError.signInMessage.other":"%s"'

EDITS = [
    (
        "zh-TW",
        "請在本服務網址後加上 /console/ 開啟終端機登入 {agent}（Claude 請執行 claude login），"
        "或到 WoowTech 平台的服務設定填入 API Key；也可以到「設定 → 模型與供應商」改用 OpenCode。",
        "請點 OpenDesign 頁面右下角的「CLI Terminal」開啟終端機登入 {agent}（Claude 請執行 claude 後輸入 /login），"
        "或到「設定 → 模型與供應商」填入 API Key 或改用 OpenCode，再重新嘗試。",
    ),
    (
        "zh-CN",
        "请在本服务网址后加上 /console/ 打开终端登录 {agent}（Claude 请运行 claude login），"
        "或到 WoowTech 平台的服务设置填入 API Key；也可以到「设置 → 模型与供应商」改用 OpenCode。",
        "请点 OpenDesign 页面右下角的「CLI Terminal」打开终端登录 {agent}（Claude 请运行 claude 后输入 /login），"
        "或到「设置 → 模型与供应商」填入 API Key 或改用 OpenCode，再重新尝试。",
    ),
    (
        "en",
        "Sign in to {agent} first, then try again.",
        "Sign in to {agent} in the CLI Terminal (the button at the bottom right of the OpenDesign page; "
        "for Claude, run claude and then /login), or add an API key or switch to OpenCode in "
        "Settings → Models & providers, then try again.",
    ),
]

# PaaS-only wording that must not reach a Home Assistant user.
FORBIDDEN = ("/console/", "WoowTech 平台的服務設定", "WoowTech 平台的服务设置")


def main(outdir):
    chunks = os.path.join(outdir, "_next", "static", "chunks")
    files = sorted(os.path.join(chunks, f) for f in os.listdir(chunks) if f.endswith(".js"))
    src = {p: open(p, encoding="utf-8").read() for p in files}
    new = dict(src)
    log = []
    for locale, old, rep in EDITS:
        needle = KEY % old
        hits = [(p, s.count(needle)) for p, s in new.items() if needle in s]
        if len(hits) != 1 or hits[0][1] != 1:
            sys.exit(f"sign-in-hint: {locale}: expected exactly 1 match of the core text, got {hits}")
        path = hits[0][0]
        new[path] = new[path].replace(needle, KEY % rep)
        log.append(f"{locale}: {os.path.basename(path)}")
    for bad in FORBIDDEN:
        left = [os.path.basename(p) for p, s in new.items() if bad in s]
        if left:
            sys.exit(f"sign-in-hint: PaaS wording '{bad}' still in {left}")
    for path, text in new.items():
        if text != src[path]:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
    print("sign-in-hint: " + "; ".join(log))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: sign-in-hint.py <web out dir>")
    main(sys.argv[1])
