# -*- coding: utf-8 -*-
"""无 UI 端到端测试：直接跑 证书安装线程（真实 adb、真实设备）。"""
import importlib.util
import subprocess
import sys

sys.path.insert(0, r"G:\Python\jcspy\Super_ADB\Super_ADB_Win")
from PySide6.QtCore import QCoreApplication

应用 = QCoreApplication([])

spec = importlib.util.spec_from_file_location(
    "证书安装对话框", r"G:\Python\jcspy\Super_ADB\Super_ADB_Win\对话框\证书安装对话框.py")
模块 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(模块)

序列号 = "192.168.75.3:5555"
证书 = r"C:\Users\57676\Desktop\Desktop.pem"


class 假adbc:
    def 执行shell(self, 序列号, 命令, timeout=30):
        结果 = subprocess.run(["adb", "-s", 序列号, "shell", 命令],
                            capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
        return (结果.stdout or "") + (结果.stderr or "")

    def 直接执行(self, 序列号, 参数, timeout=30):
        结果 = subprocess.run(["adb", "-s", 序列号] + list(参数),
                            capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
        输出 = (结果.stdout or "") + (结果.stderr or "")
        if 结果.returncode != 0:
            raise RuntimeError(输出.strip() or f"adb 退出码 {结果.returncode}")
        return 输出


def 跑一次(标题):
    print("=" * 70, flush=True)
    print(标题, flush=True)
    线程 = 模块.证书安装线程(假adbc(), 序列号, "安装证书", 证书路径=证书)
    线程.日志.connect(lambda s: print(s, flush=True))
    结果 = {}
    线程.完成.connect(lambda 成功, 消息: 结果.update(成功=成功, 消息=消息))
    线程.run()
    print(f">>> 结果: {结果}", flush=True)
    return 结果.get("成功")


if __name__ == "__main__":
    成功1 = 跑一次("场景A：模拟重启后（根分区满盘、cacerts 未挂 tmpfs）")
    成功2 = 跑一次("场景B：已桥接状态下再次安装（快路径）")
    print("=" * 70)
    print(f"A 满盘场景成功={成功1} / B 快路径成功={成功2}")
