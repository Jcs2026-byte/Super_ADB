# -*- coding: utf-8 -*-
r"""
企业微信客户继承独立版 · Win7 一键打包
======================================
用法（在本目录下）：
    py -3.8 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python 打包.py

产物：dist\企业微信客户继承.exe （单文件，可直接拷到 Win7 运行）
"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _F运行(cmd):
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, cwd=_HERE)
    if r.returncode != 0:
        raise SystemExit(f"失败 exit={r.returncode}")


def main():
    # 优先用 venv 里的 python；否则要求当前解释器就是 3.8
    if sys.platform == "win32":
        venv_py = os.path.join(_HERE, ".venv", "Scripts", "python.exe")
    else:
        venv_py = os.path.join(_HERE, ".venv", "bin", "python")
    py = venv_py if os.path.isfile(venv_py) else sys.executable

    # 校验版本
    v = subprocess.check_output([py, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"], text=True).strip()
    print(f"打包用 Python: {v} ({py})")
    if not v.startswith("3.8"):
        print("[警告] 推荐用 Python 3.8（Win7 兼容），当前版本", v)

    _F运行([
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        # 我们只用 ThreadPoolExecutor（线程），不用 multiprocessing（进程）。
        # PyInstaller 默认注入 multiprocessing runtime hook，在 Win7 上会因为
        # _socket.pyd 加载失败崩在启动期，直接排除。
        "--exclude-module", "multiprocessing",
        "--exclude-module", "numpy",
        "--exclude-module", "pytest",
        "--name", "企业微信客户继承",
        os.path.join(_HERE, "main.py"),
    ])
    print("\n打包完成：", os.path.join(_HERE, "dist", "企业微信客户继承", "企业微信客户继承.exe"))
    print("分发：把整个 dist\\企业微信客户继承 文件夹拷到目标机器，双击里面的 exe 运行")


if __name__ == "__main__":
    main()
