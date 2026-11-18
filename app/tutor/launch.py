#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
launch.py: 本地医学伴学系统极速启动器
启动后台 server.py 并唤起系统默认浏览器。
"""

import sys
import time
import urllib.request
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
PORT = 8766
BASE_URL = f"http://127.0.0.1:{PORT}"

def is_server_running():
    try:
        # 强制不使用任何系统代理，直连 127.0.0.1
        no_proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(no_proxy_handler)
        req = urllib.request.Request(f"{BASE_URL}/api/units", headers={"Host": f"127.0.0.1:{PORT}"})
        with opener.open(req, timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False

def main():
    # 任意已注册 unit 均可通过命令行参数打开；中文别名只保留历史兼容。
    target_unit = "asthma"
    if len(sys.argv) > 1:
        raw = sys.argv[1].strip()
        aliases = {"008": "asthma", "哮喘": "asthma", "004": "pte", "肺栓塞": "pte"}
        target_unit = aliases.get(raw.lower(), raw)

    target_url = f"{BASE_URL}/?unit={quote(target_unit)}"

    print("=" * 60)
    print("   考研西医综合 · 伴随式医学教辅系统 (主讲课程原讲义)")
    print(f"   当前单元：{target_unit}")
    print(f"   访问地址：{target_url}")
    print("=" * 60)

    if not is_server_running():
        print("正在启动后台伴学服务 server.py ...")
        server_py = HERE / "server.py"
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        out_log = open(HERE / "runtime-out.log", "a", encoding="utf-8")
        err_log = open(HERE / "runtime-error.log", "a", encoding="utf-8")

        subprocess.Popen(
            [sys.executable, "-u", str(server_py), "--port", str(PORT)],
            cwd=str(HERE),
            stdout=out_log,
            stderr=err_log,
            creationflags=creationflags,
            close_fds=True
        )
        # 等待 1.5 秒让服务就绪
        time.sleep(1.5)

    print(f"正在唤起默认浏览器打开：{target_url}")
    try:
        webbrowser.open(target_url)
    except Exception as e:
        print("唤起浏览器失败：", e)

    print("已在浏览器中打开，本窗口将在 2 秒后自动关闭。")
    time.sleep(2)

if __name__ == "__main__":
    main()
