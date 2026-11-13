# -*- coding: utf-8 -*-
"""真机集成测试：定时刷新是否只刷「最新展开的那一个目录」（且能刷出新文件）。"""
import sys
import time

sys.path.insert(0, r"G:\Python\jcspy\Super_ADB\Super_ADB_Win")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QStandardItem
from PySide6.QtCore import Qt

应用 = QApplication([])
from 页面.文件管理页 import 文件管理页, LOADED_ROLE  # noqa: E402

序列号 = "192.168.75.25:5555"
探测文件 = "/data/local/_refresh_probe.txt"

页 = 文件管理页()
页._device_mgr_on = True
页._current_serial = 序列号
页._root_path = '/'
记录 = []
原刷新 = 页._refresh_dir


def 包装刷新(路径, **额外):
    记录.append(路径)
    return 原刷新(路径, **额外)


页._refresh_dir = 包装刷新
页._build_root()


def 等待(条件, 说明, 超时=25):
    起 = time.time()
    while time.time() - 起 < 超时:
        应用.processEvents()
        if 条件():
            print(f"  ✓ {说明}（{time.time() - 起:.1f}s）")
            return True
        time.sleep(0.05)
    print(f"  ✗ 超时: {说明}")
    return False


def 找子项(父路径, 子路径):
    父 = 页._dir_items.get(父路径)
    if 父 is None:
        return None
    for r in range(父.rowCount()):
        项 = 父.child(r, 0)
        if 项 and (项.data(Qt.UserRole) or {}).get('path') == 子路径:
            return 项
    return None


print("1) 加载根目录 /")
assert 等待(lambda: 页._dir_items.get('/') and 页._dir_items['/'].rowCount() > 1, "根目录加载")

print("2) 展开 /data")
数据项 = 找子项('/', '/data')
assert 数据项 is not None, "根目录里没有 /data"
页.tree.setExpanded(数据项.index(), True)
assert 等待(lambda: 数据项.data(LOADED_ROLE) and 数据项.rowCount() > 1, "/data 加载")

print("3) 展开 /data/local")
本地项 = 找子项('/data', '/data/local')
assert 本地项 is not None, "/data 下没有 /data/local"
页.tree.setExpanded(本地项.index(), True)
assert 等待(lambda: 本地项.data(LOADED_ROLE) and 本地项.rowCount() > 1, "/data/local 加载")
旧子项 = 本地项.rowCount()

print("4) 在设备上新增文件，然后触发定时刷新")
import subprocess
subprocess.run(["adb", "-s", 序列号, "shell", f"rm -f {探测文件}"], check=True, capture_output=True)
记录.clear()
页._on_auto_refresh()
assert 等待(lambda: 找子项('/data/local', 探测文件) is None, "旧探测文件已从列表消失")
subprocess.run(["adb", "-s", 序列号, "shell", f"echo probe > {探测文件}"], check=True, capture_output=True)
记录.clear()
页._on_auto_refresh()
assert 等待(lambda: 找子项('/data/local', 探测文件) is not None, "新增文件出现在已展开的 /data/local 下")
print("   记录到的最新展开路径 =", 页._最近展开路径)
assert 页._最近展开路径 == '/data/local', 页._最近展开路径
print("   本次刷新发出的目录 =", [repr(路径) for 路径 in 记录])
assert 记录 == ['/data/local'], [repr(路径) for 路径 in 记录]
assert '/data' not in 记录, "父目录 /data 不该被自动刷新"
assert '/' not in 记录, "根目录 / 不该被自动刷新"

print("5) 删除探测文件后再刷新，行应消失")
subprocess.run(["adb", "-s", 序列号, "shell", f"rm -f {探测文件}"], check=True, capture_output=True)
记录.clear()
页._on_auto_refresh()
assert 等待(lambda: 找子项('/data/local', 探测文件) is None, "删除后行已从展开目录消失")

print("全部通过")
