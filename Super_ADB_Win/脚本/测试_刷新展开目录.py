# -*- coding: utf-8 -*-
"""验证定时刷新只刷「最新展开的那一个目录」。"""
import sys
import types

sys.path.insert(0, r"G:\Python\jcspy\Super_ADB\Super_ADB_Win")
from PySide6.QtWidgets import QApplication, QTreeView
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt

应用 = QApplication([])

from 页面.文件管理页 import 文件管理页, LOADED_ROLE  # noqa: E402


class 假记录:
    def __init__(self):
        self.tree = QTreeView()
        self.model = QStandardItemModel()
        self.tree.setModel(self.model)
        self._dir_items = {}
        self._loading = set()
        self._root_path = '/'
        self._last_browsed_path = '/'
        self._最近展开路径 = '/'
        self._current_serial = 'TEST'
        self._deep_search_mode = False
        self._device_mgr_on = True
        self.刷新记录 = []
        self.状态 = []
        for 名 in ('_on_auto_refresh', '_刷新目录树', '_收集已展开目录'):
            setattr(self, 名, types.MethodType(getattr(文件管理页, 名), self))

    def _status(self, 文本):
        self.状态.append(文本)

    def _refresh_dir(self, 路径, 记录=True):
        self.刷新记录.append(路径)


def 造节点(假, 路径, 名称):
    节点 = QStandardItem(名称)
    节点.setData({'is_dir': True, 'path': 路径, 'name': 名称}, Qt.UserRole)
    节点.setData(False, LOADED_ROLE)
    节点.appendRow(QStandardItem(''))
    假._dir_items[路径] = 节点
    return 节点


假 = 假记录()
根 = 造节点(假, '/', '/')
假.model.appendRow([根])
数据 = 造节点(假, '/data', 'data')
根.appendRow([数据])
本地 = 造节点(假, '/data/local', 'local')
数据.appendRow([本地])
临时 = 造节点(假, '/data/local/tmp', 'tmp')
本地.appendRow([临时])
假.tree.setExpanded(根.index(), True)
假.tree.setExpanded(数据.index(), True)
假.tree.setExpanded(本地.index(), True)

假.刷新记录.clear()
假._最近展开路径 = '/data/local'
假._on_auto_refresh()
print('最新展开=/data/local → 定时刷新 =', 假.刷新记录)
assert 假.刷新记录 == ['/data/local'], 假.刷新记录

假.刷新记录.clear()
假._最近展开路径 = '/data/local/tmp'
假._on_auto_refresh()
print('再展开 tmp → 定时刷新 =', 假.刷新记录)
assert 假.刷新记录 == ['/data/local/tmp'], 假.刷新记录

假.刷新记录.clear()
假._最近展开路径 = '/ghost'  # 目录已被删除
假._last_browsed_path = '/data'
假._on_auto_refresh()
print('展开路径失效 → 回退 =', 假.刷新记录)
assert 假.刷新记录 == ['/data'], 假.刷新记录

假.tree.setExpanded(临时.index(), True)
print('全部展开目录 =', 假._收集已展开目录('/'))
假.刷新记录.clear()
假._刷新目录树('/data')
print('手动刷新 /data（子树）=', 假.刷新记录)
assert 假.刷新记录 == ['/data', '/data/local', '/data/local/tmp'], 假.刷新记录

print('全部通过')
