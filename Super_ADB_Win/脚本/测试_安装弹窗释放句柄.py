# -*- coding: utf-8 -*-
"""回归测试：close / ✕(reject) / hide / 加载中关闭，四种方式都必须释放 APK 句柄。"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, r"G:\Python\jcspy\Super_ADB\Super_ADB_Win")
from PySide6.QtWidgets import QApplication

应用 = QApplication([])
from 对话框.安装解包对话框 import 安装解包对话框  # noqa: E402

小包 = r"C:\Users\57676\Desktop\MessageMigu_release_v6000.1.9_60000019_202609201539_signed.apk"
大包 = r"C:\Users\57676\Desktop\app-release-2.0.6-20261013.075952-49.apk"


def 转(秒=1.0, 条件=None):
    起 = time.time()
    while time.time() - 起 < 秒:
        应用.processEvents()
        if 条件 and 条件():
            return True
        time.sleep(0.02)
    return bool(条件()) if 条件 else True


def 跑(名称, 源, 步骤):
    目录 = tempfile.mkdtemp(prefix="apklock_")
    目标 = os.path.join(目录, "target.apk")
    shutil.copy(源, 目标)
    弹窗 = 安装解包对话框(None, lambda: "192.168.75.25:5555")
    弹窗.show()
    弹窗.open_package(目标)
    if 源 == 小包:
        转(6, lambda: 弹窗._zf is not None and 弹窗.tree.topLevelItemCount() > 0)
        项 = 弹窗.tree.topLevelItem(0)
        if 项:
            弹窗._on_item_clicked(项, 0)
        转(0.4)
        步骤(弹窗)
    else:
        转(0.05)
        步骤(弹窗)
    转(2.5)
    time.sleep(1.0)
    转(0.5)
    try:
        os.remove(目标)
        结果 = "可删除 ✓"
    except Exception as 错:
        结果 = f"仍占用 ✗ ({type(错).__name__}: {错})"
    print(f"{名称}: _zf={弹窗._zf} → {结果}")
    try:
        if 弹窗._zf is not None:
            弹窗._zf.close()
    except Exception:
        pass
    shutil.rmtree(目录, ignore_errors=True)
    return 结果.endswith("✓")


结果 = []
结果.append(跑("① 底部『关闭』close()", 小包, lambda d: d.close()))
结果.append(跑("② 标题栏 ✕ reject()", 小包, lambda d: d.reject()))
结果.append(跑("③ 宿主 hide()", 小包, lambda d: d.hide()))
结果.append(跑("④ 51MB 加载中立即 ✕", 大包, lambda d: d.reject()))
print("\n全部通过" if all(结果) else "\n存在未释放的情况")
