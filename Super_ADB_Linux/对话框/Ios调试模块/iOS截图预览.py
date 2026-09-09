# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS截图预览.py
=====================================
iOS 设备截图：后台执行 ios screenshot --output=… → 预览 + 另存为。
（新建代码遵循 c/f/b 前缀 + 中文命名。）
"""
import os
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
)

from 项目UI.对话框基类 import 对话框基类
from 对话框.Ios调试模块.公共任务 import c任务桥


class c图像标签(QLabel):
    """自适应缩放显示图片的标签（keep aspect ratio）。"""

    def __init__(self, _b父窗口=None):
        super().__init__(_b父窗口)
        self._b原始图 = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 200)

    def f设置图片(self, _b位图):
        self._b原始图 = _b位图
        self._f重排图片()

    def resizeEvent(self, _b事件):
        super().resizeEvent(_b事件)
        self._f重排图片()

    def _f重排图片(self):
        if self._b原始图 is None:
            return
        _b可用宽 = max(1, self.width() - 4)
        _b可用高 = max(1, self.height() - 4)
        self.setPixmap(self._b原始图.scaled(
            _b可用宽, _b可用高,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


class cIos截图预览对话框(对话框基类):
    """iOS 截图预览弹窗。"""

    def __init__(self, _bios工具, _budid, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 截图预览', 最小尺寸=(820, 600), 发光=True)
        self._bios工具 = _bios工具
        self._budid = _budid or ''
        self._b当前截图路径 = ''
        self._b桥 = c任务桥(self)
        self._b桥._b完成信号.connect(self.f截图完成时)
        self._f构建界面()
        self.f开始截图()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b顶部行 = QHBoxLayout()
        _b提示 = QLabel(f'目标设备：{self._budid[:24] + "…" if len(self._budid) > 24 else self._budid}')
        _b提示.setStyleSheet('font-size:12px; opacity:0.85;')
        _b顶部行.addWidget(_b提示)
        _b顶部行.addStretch(1)
        self._b再截图按钮 = QPushButton('重新截图')
        self._b再截图按钮.clicked.connect(self.f开始截图)
        self._b另存按钮 = QPushButton('另存为…')
        self._b另存按钮.clicked.connect(self.f另存为)
        self._b另存按钮.setEnabled(False)
        _b顶部行.addWidget(self._b再截图按钮)
        _b顶部行.addWidget(self._b另存按钮)
        _b外层.addLayout(_b顶部行)

        _b滚动 = QScrollArea()
        _b滚动.setWidgetResizable(True)
        self._b图片标签 = c图像标签()
        _b滚动.setWidget(self._b图片标签)
        _b外层.addWidget(_b滚动, stretch=1)

        self._b状态标签 = QLabel('正在截图…')
        self._b状态标签.setStyleSheet('font-size:12px;')
        _b外层.addWidget(self._b状态标签)

    # ------------------------------------------------------------------
    def f开始截图(self):
        self._b再截图按钮.setEnabled(False)
        self._b另存按钮.setEnabled(False)
        self._b状态标签.setText('正在执行 ios screenshot …')
        _b目录 = os.path.join(tempfile.gettempdir(), 'Super_ADB_ios')
        os.makedirs(_b目录, exist_ok=True)
        _b文件 = os.path.join(
            _b目录,
            f'ios截图_{time.strftime("%H%M%S")}_{os.getpid()}.png')
        self._b桥.f执行(self._bios工具.f截图, self._budid, _b文件)

    def f截图完成时(self, _b结果):
        self._b再截图按钮.setEnabled(True)
        if isinstance(_b结果, Exception):
            self._b状态标签.setText(f'截图失败：{_b结果}')
            return
        _b路径 = str(_b结果)
        _b位图 = QPixmap(_b路径)
        if _b位图.isNull():
            self._b状态标签.setText(f'截图完成但无法读取图片：{_b路径}')
            return
        self._b当前截图路径 = _b路径
        self._b图片标签.f设置图片(_b位图)
        self._b另存按钮.setEnabled(True)
        _b大小 = os.path.getsize(_b路径)
        self._b状态标签.setText(
            f'截图成功：{_b路径}（{_b大小 / 1024:.0f} KB）')

    def f另存为(self):
        if not self._b当前截图路径:
            return
        _b默认名 = os.path.join(
            os.path.expanduser('~'), 'Desktop', 'ios截图.png') if os.path.isdir(
            os.path.expanduser('~/Desktop')) else self._b当前截图路径
        _b保存路径, _ = QFileDialog.getSaveFileName(
            self, '另存 iOS 截图', _b默认名, '图片文件 (*.png *.jpg)')
        if not _b保存路径:
            return
        if self._b图片标签._b原始图 is not None:
            _b位图 = self._b图片标签._b原始图
        else:
            _b位图 = QPixmap(self._b当前截图路径)
        _b是否成功 = _b位图.save(_b保存路径)
        self._b状态标签.setText(
            f'已另存到：{_b保存路径}' if _b是否成功 else f'另存失败：{_b保存路径}')
