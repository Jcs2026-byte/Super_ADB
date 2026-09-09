# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS日志对话框.py
========================================
iOS 系统日志跟随：
    子进程跑 ios syslog → 后台线程逐行入队 → 主线程 QTimer 缓冲批量追加，
    避免高频信号打爆 UI。支持 开始/停止 切换、清屏、复制。
（新建代码遵循 c/f/b 前缀 + 中文命名。）
"""
import queue
import subprocess
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from 项目UI.对话框基类 import 对话框基类

_bWIN = sys.platform.startswith('win')
_b最大日志行 = 8000      # 超出后丢弃头部
_b裁剪步长 = 2000       # 每次超限裁剪行数
_b刷新间隔毫秒 = 200    # 队列 → UI 刷新周期


class cIos日志跟随对话框(对话框基类):
    """实时跟随 ios syslog 输出。"""

    def __init__(self, _bios工具, _budid, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 系统日志（跟随）', 最小尺寸=(760, 560), 发光=True)
        self._bios工具 = _bios工具
        self._budid = _budid or ''
        self._b进程 = None
        self._b线程 = None
        self._b队列 = queue.Queue()
        self._b运行中 = False
        self._f构建界面()
        self.f开始()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b顶部行 = QHBoxLayout()
        self._b状态标签 = QLabel('准备就绪')
        _b顶部行.addWidget(self._b状态标签)
        _b顶部行.addStretch(1)
        self._b开始按钮 = QPushButton('停止')
        self._b开始按钮.clicked.connect(self.f切换开始停止)
        _b清屏按钮 = QPushButton('清屏')
        _b清屏按钮.clicked.connect(self._b日志框.clear)
        _b复制按钮 = QPushButton('复制')
        _b复制按钮.clicked.connect(self.f复制日志)
        _b顶部行.addWidget(_b清屏按钮)
        _b顶部行.addWidget(_b复制按钮)
        _b顶部行.addWidget(self._b开始按钮)
        _b外层.addLayout(_b顶部行)

        self._b日志框 = QPlainTextEdit()
        self._b日志框.setReadOnly(True)
        _b字体 = QFont('Consolas')
        _b字体.setStyleHint(QFont.StyleHint.Monospace)
        _b字体.setPointSize(9)
        self._b日志框.setFont(_b字体)
        _b外层.addWidget(self._b日志框, stretch=1)

        self._b刷新计时器 = QTimer(self)
        self._b刷新计时器.setInterval(_b刷新间隔毫秒)
        self._b刷新计时器.timeout.connect(self.f批量刷新)

    # ------------------------------------------------------------------
    def f开始(self):
        if self._b运行中 or not self._bios工具.f可用():
            return
        _b命令 = self._bios工具.f构造命令(self._budid, 'syslog')
        try:
            self._b进程 = subprocess.Popen(
                _b命令,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0,
            )
        except FileNotFoundError:
            from 工具.Ios调试模块.goIos桥接 import f安装指引
            self._b状态标签.setText('启动失败：' + f安装指引())
            return
        except OSError as _b异常:
            self._b状态标签.setText(f'启动失败：{_b异常}')
            return
        self._b运行中 = True
        self._b开始按钮.setText('停止')
        self._b状态标签.setText('正在跟随 ios syslog …（iOS 17+ 需已建立隧道）')
        self._b线程 = threading.Thread(target=self._f读进程, daemon=True)
        self._b线程.start()
        self._b刷新计时器.start()

    def _f读进程(self):
        """后台：逐行读 stdout 入队；进程退出或外部停止时结束。"""
        try:
            while self._b运行中 and self._b进程 is not None:
                _b行 = self._b进程.stdout.readline()
                if not _b行:
                    break
                self._b队列.put(_b行)
        except Exception:
            pass
        finally:
            self._b队列.put(None)  # EOF 哨兵

    def f批量刷新(self):
        """定时把缓冲队列追加到文本框（一次最多一批，防止刷屏卡顿）。"""
        _b片段 = []
        _b收到结束 = False
        while True:
            try:
                _b行 = self._b队列.get_nowait()
            except queue.Empty:
                break
            if _b行 is None:
                _b收到结束 = True
                break
            _b片段.append(_b行.rstrip('\n'))
        if _b片段:
            self._b日志框.appendPlainText('\n'.join(_b片段))
            self._f裁剪行数()
            # 跟随到底部
            _b滚动条 = self._b日志框.verticalScrollBar()
            _b滚动条.setValue(_b滚动条.maximum())
        if _b收到结束:
            self._f进程结束()

    def _f裁剪行数(self):
        _b块 = self._b日志框.document().firstBlock()
        while self._b日志框.document().blockCount() > _b最大日志行:
            _b光标 = QTextCursor(_b块)
            _b光标.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                 QTextCursor.MoveMode.KeepAnchor)
            _b光标.removeSelectedText()
            _b光标.deleteChar()  # 删除换行符
            _b块 = _b块.next()

    def _f进程结束(self):
        self._b运行中 = False
        self._b刷新计时器.stop()
        self._b开始按钮.setText('重新开始')
        self._b状态标签.setText('日志流已结束（进程退出或设备断开）')

    def f切换开始停止(self):
        if self._b运行中:
            self.f停止()
            self._b开始按钮.setText('重新开始')
        else:
            self.f开始()

    def f停止(self):
        self._b运行中 = False
        self._b刷新计时器.stop()
        if self._b进程 is not None and self._b进程.poll() is None:
            try:
                self._b进程.terminate()
            except Exception:
                pass
        if self._b线程 is not None:
            self._b线程.join(timeout=2)
        self._b进程 = None
        self._b线程 = None
        self._b状态标签.setText('已停止')

    def f复制日志(self):
        QApplication.clipboard().setText(self._b日志框.toPlainText())
        self._b状态标签.setText('日志已复制到剪贴板')

    def closeEvent(self, _b事件):
        self.f停止()
        super().closeEvent(_b事件)
