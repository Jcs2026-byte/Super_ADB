# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS代理设置对话框.py
============================================
iOS 全局 HTTP 代理管理（抓包刚需，pymobiledevice3 独有能力）：
    - 设置代理：profile install-http-proxy <server> <port>
    - 清除代理：profile remove-http-proxy
    - 查询当前：profile list（列出已装描述文件，含代理）
    - 安装证书：profile install <证书路径>（HTTPS 解密）
复用 c任务桥 后台执行，风格与同目录其它对话框一致（c/f/b 前缀 + 中文命名）。
"""
import json

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTextEdit,
    QVBoxLayout, QFileDialog, QApplication,
)

from 项目UI.对话框基类 import 对话框基类
from 对话框.Ios调试模块.公共任务 import c任务桥


class cIos代理设置对话框(对话框基类):
    """iOS 全局 HTTP 代理设置弹窗（含 SSL 证书安装）。"""

    def __init__(self, _bios工具, _budid, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 代理设置', 最小尺寸=(640, 560), 发光=True)
        self._bios工具 = _bios工具
        self._budid = _budid or ''
        self._b桥 = c任务桥(self)
        self._b桥._b完成信号.connect(self.f完成时)
        self._f构建界面()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b设备标签 = QLabel(f'UDID：{self._budid or "（默认第一台设备）"}')
        _b设备标签.setStyleSheet('font-size:12px; opacity:0.85;')
        _b外层.addWidget(_b设备标签)

        # 代理服务器 + 端口
        _b代理行 = QHBoxLayout()
        _b代理行.addWidget(QLabel('代理服务器：'))
        self._b服务器输入 = QLineEdit()
        self._b服务器输入.setPlaceholderText('本机(电脑)IP，例如 192.168.1.10')
        _b代理行.addWidget(self._b服务器输入, stretch=1)
        _b代理行.addWidget(QLabel('端口：'))
        self._b端口输入 = QSpinBox()
        self._b端口输入.setRange(1, 65535)
        self._b端口输入.setValue(8888)
        _b代理行.addWidget(self._b端口输入)
        _b外层.addLayout(_b代理行)

        # 操作按钮行 1：代理三件套
        _b按钮行1 = QHBoxLayout()
        _b设置按钮 = QPushButton('设置代理')
        _b设置按钮.clicked.connect(self.f设置代理)
        _b清除按钮 = QPushButton('清除代理')
        _b清除按钮.clicked.connect(self.f清除代理)
        _b查询按钮 = QPushButton('查询当前')
        _b查询按钮.clicked.connect(self.f查询当前)
        _b按钮行1.addWidget(_b设置按钮)
        _b按钮行1.addWidget(_b清除按钮)
        _b按钮行1.addWidget(_b查询按钮)
        _b按钮行1.addStretch(1)
        _b外层.addLayout(_b按钮行1)

        # 操作按钮行 2：证书安装
        _b按钮行2 = QHBoxLayout()
        _b证书按钮 = QPushButton('安装 SSL 证书…')
        _b证书按钮.setToolTip(
            '安装 mitmproxy/Charles 的根证书，用于解密 HTTPS 流量（抓 HTTPS 必装）')
        _b证书按钮.clicked.connect(self.f安装证书)
        _b按钮行2.addWidget(_b证书按钮)
        _b按钮行2.addStretch(1)
        _b外层.addLayout(_b按钮行2)

        # 输出区
        self._b输出框 = QTextEdit()
        self._b输出框.setReadOnly(True)
        self._b输出框.setPlaceholderText('操作结果将显示在这里…')
        _b外层.addWidget(self._b输出框, stretch=1)

        # 底部说明
        _b说明 = QLabel(
            '抓包流程：① 设置代理（本机 IP:端口，抓包工具监听该端口）→ ② 安装 SSL 证书'
            '（HTTPS 解密）→ ③ 设备「设置 → 通用 → VPN 与设备管理」确认描述文件 → '
            '④ 开始抓包。完成后点「清除代理」还原。')
        _b说明.setWordWrap(True)
        _b说明.setStyleSheet('font-size:11px; opacity:0.7;')
        _b外层.addWidget(_b说明)

    # ------------------------------------------------------------------
    def _f记录(self, _b文本):
        self._b输出框.append(str(_b文本))

    def f完成时(self, _b结果):
        if isinstance(_b结果, Exception):
            self._f记录(f'操作失败：{_b结果}')
            return
        if isinstance(_b结果, (dict, list)):
            self._f记录(json.dumps(_b结果, ensure_ascii=False, indent=2))
            return
        self._f记录(str(_b结果) if _b结果 is not None else '（无输出）')

    # ------------------------------------------------------------------
    def _f取服务器(self):
        _b服务器 = self._b服务器输入.text().strip()
        if not _b服务器:
            self._f记录('请先填写代理服务器地址（本机 IP）')
            return None
        return _b服务器

    def f设置代理(self):
        _b服务器 = self._f取服务器()
        if not _b服务器:
            return
        _b端口 = self._b端口输入.value()
        self._f记录(f'$ profile install-http-proxy {_b服务器} {_b端口} …')
        self._b桥.f执行(self._bios工具.f安装HTTP代理, self._budid, _b服务器, _b端口)

    def f清除代理(self):
        self._f记录('$ profile remove-http-proxy …')
        self._b桥.f执行(self._bios工具.f移除HTTP代理, self._budid)

    def f查询当前(self):
        self._f记录('$ profile list …')
        self._b桥.f执行(self._bios工具.f列出描述文件, self._budid)

    def f安装证书(self):
        _b路径, _ = QFileDialog.getOpenFileName(
            self, '选择 SSL 证书 / 描述文件', '',
            '证书与描述文件 (*.pem *.crt *.cer *.der *.mobileconfig);;所有文件 (*)')
        if not _b路径:
            return
        self._f记录(f'$ profile install {_b路径} …')
        self._b桥.f执行(self._bios工具.f安装描述文件, self._budid, _b路径)
