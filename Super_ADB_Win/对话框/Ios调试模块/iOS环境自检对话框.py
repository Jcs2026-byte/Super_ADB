# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS环境自检对话框.py
============================================
对应 iOS 接入方案 §8 的「iOS 环境自检」面板：
逐项校验 二进制存在 → ios version → 设备枚举 → 隧道状态 → 开发者模式 → 镜像挂载，
红绿灯展示并给修复指引。风格与现有 诊断/ 模块一致（新建代码 c/f/b 前缀命名）。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTextEdit, QVBoxLayout, QApplication,
)

from 项目UI.对话框基类 import 对话框基类
from 对话框.Ios调试模块.公共任务 import c任务桥

# 状态 → 显示色 / 中文标签
_b状态配色 = {
    'ok':   ('#3ddc84', '正常'),
    'warn': ('#ffd740', '注意'),
    'bad':  ('#ff5252', '异常'),
    'none': ('#9e9e9e', '跳过'),
}


class cIos环境自检对话框(对话框基类):
    """iOS 环境逐项自检弹窗。"""

    def __init__(self, _bios工具, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 环境自检', 最小尺寸=(660, 560), 发光=True)
        self._bios工具 = _bios工具
        self._b报告行 = []
        self._b桥 = c任务桥(self)
        self._b桥._b完成信号.connect(self.f自检完成时)
        self._f构建界面()
        self.f开始自检()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b标题行 = QHBoxLayout()
        _b标题 = QLabel('逐项校验 go-ios 后端可用性（安装指引见底部）')
        _b标题.setStyleSheet('font-size:13px; opacity:0.85;')
        _b标题行.addWidget(_b标题)
        _b标题行.addStretch(1)
        _b重试按钮 = QPushButton('重新自检')
        _b重试按钮.clicked.connect(self.f开始自检)
        _b复制按钮 = QPushButton('复制报告')
        _b复制按钮.clicked.connect(self.f复制报告)
        _b标题行.addWidget(_b重试按钮)
        _b标题行.addWidget(_b复制按钮)
        _b外层.addLayout(_b标题行)

        self._b列表 = QListWidget()
        self._b列表.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._b列表.currentItemChanged.connect(self.f显示指引)
        _b外层.addWidget(self._b列表, stretch=3)

        _b指引标题 = QLabel('修复指引')
        _b指引标题.setStyleSheet('font-size:12px; font-weight:600;')
        _b外层.addWidget(_b指引标题)
        self._b指引框 = QTextEdit()
        self._b指引框.setReadOnly(True)
        self._b指引框.setPlaceholderText('选中上方任一检查项，这里显示修复指引…')
        _b外层.addWidget(self._b指引框, stretch=2)

    # ------------------------------------------------------------------
    def f开始自检(self):
        """后台跑环境自检，避免阻塞 UI。"""
        self._b列表.clear()
        self._b报告行 = []
        self._b指引框.setPlainText('正在逐项自检…（设备相关项需已连接 iOS 设备）')
        self._b桥.f执行(self._bios工具.f执行环境自检)

    def f自检完成时(self, _b结果):
        _b报告行 = _b结果 if isinstance(_b结果, list) else None
        if _b报告行 is None:
            _b异常文本 = str(_b结果) if isinstance(_b结果, Exception) else str(_b结果)
            _b报告行 = [{
                '名称': '自检异常', '状态': 'bad',
                '信息': _b异常文本,
                '指引': '尝试「重新自检」，或以管理员身份运行本工具后重试',
            }]
        self._b报告行 = _b报告行
        for _b序号, _b项 in enumerate(_b报告行, start=1):
            _b状态码 = _b项.get('状态', 'none')
            _b色, _b标签 = _b状态配色.get(_b状态码, _b状态配色['none'])
            _b名称 = _b项.get('名称', '')
            _b信息 = _b项.get('信息', '')
            _b条目 = QListWidgetItem(
                f'<span style="color:{_b色};font-size:16px;">●</span> '
                f'<b>{_b序号}. {_b名称}</b>　'
                f'<span style="color:{_b色};font-weight:600;">[{_b标签}]</span>'
                + (f'<br><span style="color:rgba(128,128,128,1);font-size:12px;">'
                   f'{_b信息}</span>' if _b信息 else ''))
            _b条目.setData(Qt.ItemDataRole.UserRole, _b序号 - 1)
            self._b列表.addItem(_b条目)
        # 默认选中第一项（自动展示其指引）
        if self._b列表.count():
            self._b列表.setCurrentRow(0)

    def f显示指引(self, _b当前项, *_):
        if _b当前项 is None:
            return
        _b索引 = _b当前项.data(Qt.ItemDataRole.UserRole)
        if isinstance(_b索引, int) and 0 <= _b索引 < len(self._b报告行):
            _b指引 = self._b报告行[_b索引].get('指引', '') or '（无特殊指引）'
            self._b指引框.setPlainText(_b指引)

    def f复制报告(self):
        """把自检结果拼成纯文本复制到剪贴板。"""
        _b行 = ['=== iOS 环境自检报告 ===']
        for _b项 in self._b报告行:
            _b状态码 = _b项.get('状态', 'none')
            _b标签 = _b状态配色.get(_b状态码, _b状态配色['none'])[1]
            _b行.append(f"[{_b标签}] {_b项.get('名称', '')}: {_b项.get('信息', '')}")
            _b指引 = _b项.get('指引', '')
            if _b指引:
                _b行.append(f'    指引：{_b指引}')
        QApplication.clipboard().setText('\n'.join(_b行))
