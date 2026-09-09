# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS崩溃报告对话框.py
============================================
iOS 崩溃报告查看器：
    - crash ls 拉列表，JetsamEvent / jetsam 关键字自动标注 [OOM]
    - 选中条目后台拷贝并展示详情（含 OOM 段落提示）
    - 支持 导出选中 / 全部导出
（新建代码遵循 c/f/b 前缀 + 中文命名。）
"""
import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout,
)

from 项目UI.对话框基类 import 对话框基类
from 对话框.Ios调试模块.公共任务 import c任务桥

_bOOM关键字 = ('jetsamevent', 'jetsam', 'memorystatus')
_b详情截断字符 = 400_000


class cIos崩溃报告对话框(对话框基类):
    """iOS 崩溃报告列表 + 详情。"""

    def __init__(self, _bios工具, _budid, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 崩溃报告', 最小尺寸=(860, 600), 发光=True)
        self._bios工具 = _bios工具
        self._budid = _budid or ''
        self._b崩溃列表 = []
        self._b临时目录 = os.path.join(tempfile.gettempdir(), 'Super_ADB_ios_crash')
        os.makedirs(self._b临时目录, exist_ok=True)
        self._b桥 = c任务桥(self)
        self._b桥._b完成信号.connect(self.f任务完成时)
        self._f构建界面()
        self.f刷新列表()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b顶部行 = QHBoxLayout()
        _b提示 = QLabel('文件名含 JetsamEvent 的为内存压力终止（OOM），已标注')
        _b提示.setStyleSheet('font-size:12px; opacity:0.85;')
        _b顶部行.addWidget(_b提示)
        _b顶部行.addStretch(1)
        self._b刷新按钮 = QPushButton('刷新列表')
        self._b刷新按钮.clicked.connect(self.f刷新列表)
        _b导出选中按钮 = QPushButton('导出选中…')
        _b导出选中按钮.clicked.connect(lambda: self.f导出(False))
        _b全部导出按钮 = QPushButton('全部导出…')
        _b全部导出按钮.clicked.connect(lambda: self.f导出(True))
        _b顶部行.addWidget(self._b刷新按钮)
        _b顶部行.addWidget(_b导出选中按钮)
        _b顶部行.addWidget(_b全部导出按钮)
        _b外层.addLayout(_b顶部行)

        _b分栏 = QSplitter(Qt.Orientation.Horizontal)
        self._b列表 = QListWidget()
        self._b列表.currentItemChanged.connect(self.f查看详情)
        _b分栏.addWidget(self._b列表)
        self._b详情框 = QPlainTextEdit()
        self._b详情框.setReadOnly(True)
        _b详情字体 = QFont('Consolas')
        _b详情字体.setStyleHint(QFont.StyleHint.Monospace)
        self._b详情框.setFont(_b详情字体)
        _b分栏.addWidget(self._b详情框)
        _b分栏.setStretchFactor(0, 2)
        _b分栏.setStretchFactor(1, 5)
        _b外层.addWidget(_b分栏, stretch=1)

        self._b状态标签 = QLabel('')
        _b外层.addWidget(self._b状态标签)

    # ------------------------------------------------------------------
    def f刷新列表(self):
        self._b刷新按钮.setEnabled(False)
        self._b状态标签.setText('正在读取 crash ls …')
        self._b列表.clear()
        self._b崩溃列表 = []
        self._b详情框.clear()
        self._b桥.f执行(self._bios工具.f崩溃列表, self._budid)

    def f任务完成时(self, _b结果):
        self._b刷新按钮.setEnabled(True)
        if isinstance(_b结果, Exception):
            self._b状态标签.setText(f'操作失败：{_b结果}')
            return
        if isinstance(_b结果, list) and not self._b详情框.toPlainText():
            # 列表加载结果
            self._b崩溃列表 = _b结果
            if not _b结果:
                self._b状态标签.setText('设备上没有崩溃报告（无崩溃记录）')
                return
            for _b文件名 in _b结果:
                _b小写 = str(_b文件名).lower()
                _b是否OOM = any(_b关键字 in _b小写 for _b关键字 in _bOOM关键字)
                _b条目 = QListWidgetItem(
                    (('⚠️ [OOM] ' if _b是否OOM else '') + str(_b文件名)))
                _b条目.setData(Qt.ItemDataRole.UserRole, str(_b文件名))
                self._b列表.addItem(_b条目)
            self._b状态标签.setText(f'共 {len(_b结果)} 份崩溃报告')
            if self._b列表.count():
                self._b列表.setCurrentRow(0)
            return
        # 详情加载结果（字符串）
        if isinstance(_b结果, str):
            self._b详情框.setPlainText(_b结果)

    def f查看详情(self, _b当前项, *_):
        if _b当前项 is None:
            return
        _b文件名 = _b当前项.data(Qt.ItemDataRole.UserRole)
        if not _b文件名:
            return
        self._b状态标签.setText(f'正在读取 {_b文件名} …')
        self._b桥.f执行(self._f取详情, _b文件名)

    def _f取详情(self, _b文件名):
        """后台：拷贝崩溃文件到临时目录并读回内容（加 OOM 提示头）。"""
        _b内容 = self._bios工具.f读取崩溃报告(
            self._budid, _b文件名, self._b临时目录)
        _b小写 = _b文件名.lower()
        if any(_b关键字 in _b小写 for _b关键字 in _bOOM关键字):
            _b头 = ('⚠️ 该文件为 JetsamEvent（内存压力终止）类崩溃，通常由 OOM 触发。\n'
                    '排查方向：内存占用过高 / 系统内存压力 / 大图大缓存加载。\n'
                    '────────────────────────────────────────────\n')
        else:
            _b头 = ''
        if len(_b内容) > _b详情截断字符:
            _b内容 = _b内容[:_b详情截断字符] + '\n…（内容过长已截断）'
        return _b头 + _b内容

    def f导出(self, _b全部):
        if _b全部:
            if not self._b崩溃列表:
                self._b状态标签.setText('没有可导出的崩溃报告')
                return
            _b默认说明 = '导出全部'
            _b模式 = '*'
        else:
            _b当前项 = self._b列表.currentItem()
            if _b当前项 is None:
                self._b状态标签.setText('请先选中一份崩溃报告')
                return
            _b模式 = _b当前项.data(Qt.ItemDataRole.UserRole) or ''
            _b默认说明 = f'导出 {_b模式}'
        _b目录 = QFileDialog.getExistingDirectory(
            self, f'选择导出目录（{_b默认说明}）')
        if not _b目录:
            return
        self._b状态标签.setText(f'正在导出到 {_b目录} …')
        _b导出桥 = c任务桥(self)
        _b导出桥._b完成信号.connect(lambda _b结果: self.f导出完成时(_b结果, _b目录))
        _b导出桥.f执行(self._bios工具.f拷贝崩溃, self._budid, _b模式, _b目录)

    def f导出完成时(self, _b结果, _b目录):
        if isinstance(_b结果, Exception):
            self._b状态标签.setText(f'导出失败：{_b结果}')
            return
        self._b状态标签.setText(f'导出完成 → {_b目录}')
