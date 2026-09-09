# -*- coding: utf-8 -*-
"""
对话框 / Ios调试模块 / iOS设备信息对话框.py
=============================================
读取 ios info，中文映射展示常用字段，下方可切原始 JSON。
（新建代码遵循 c/f/b 前缀 + 中文命名。）
"""
import json

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSplitter, QTextBrowser, QVBoxLayout,
    QApplication,
)

from 项目UI.对话框基类 import 对话框基类
from 对话框.Ios调试模块.公共任务 import c任务桥

# go-ios ios info 键 → 中文名（多个候选键依次探测）
_b字段映射 = [
    ('设备名称', ('DeviceName',)),
    ('系统版本', ('ProductVersion',)),
    ('构建版本', ('BuildVersion',)),
    ('机型标识', ('ProductType',)),
    ('硬件平台', ('HardwarePlatform',)),
    ('序列号', ('SerialNumber',)),
    ('型号号码', ('ModelNumber',)),
    ('芯片 ID', ('ChipID',)),
    ('芯片唯一 ID', ('UniqueChipID',)),
    ('CPU 架构', ('CPUArchitecture',)),
    ('WiFi 地址', ('WiFiAddress',)),
    ('蓝牙地址', ('BluetoothAddress',)),
    ('以太网地址', ('EthernetAddress',)),
    ('机身颜色', ('DeviceColor',)),
    ('区域信息', ('RegionInfo',)),
    ('IMEI', ('InternationalMobileEquipmentIdentity',)),
    ('基带版本', ('BasebandVersion', 'BasebandStatus')),
    ('激活状态', ('ActivationState',)),
]

_b需要隐藏键 = {_b键 for _, _b键组 in _b字段映射 for _b键 in _b键组}


class cIos设备信息对话框(对话框基类):
    """iOS 设备信息弹窗（中文映射 + 原始 JSON）。"""

    def __init__(self, _bios工具, _budid, _b父窗口=None):
        super().__init__(_b父窗口, 标题='iOS 设备信息', 最小尺寸=(720, 560), 发光=True)
        self._bios工具 = _bios工具
        self._budid = _budid or ''
        self._b原始信息 = {}
        self._b桥 = c任务桥(self)
        self._b桥._b完成信号.connect(self.f加载完成时)
        self._f构建界面()
        self.f加载信息()

    # ------------------------------------------------------------------
    def _f构建界面(self):
        _b外层 = QVBoxLayout(self)
        _b顶部行 = QHBoxLayout()
        _b设备标签 = QLabel(f'UDID：{self._budid or "（默认第一台设备）"}')
        _b设备标签.setStyleSheet('font-size:12px; opacity:0.85;')
        _b顶部行.addWidget(_b设备标签)
        _b顶部行.addStretch(1)
        _b刷新按钮 = QPushButton('刷新')
        _b刷新按钮.clicked.connect(self.f加载信息)
        _b复制按钮 = QPushButton('复制 JSON')
        _b复制按钮.clicked.connect(self.f复制JSON)
        _b顶部行.addWidget(_b刷新按钮)
        _b顶部行.addWidget(_b复制按钮)
        _b外层.addLayout(_b顶部行)

        _b分栏 = QSplitter()
        self._b中文框 = QTextBrowser()
        self._b中文框.setOpenExternalLinks(False)
        self._b原始框 = QTextBrowser()
        _b分栏.addWidget(self._b中文框)
        _b分栏.addWidget(self._b原始框)
        _b分栏.setStretchFactor(0, 1)
        _b分栏.setStretchFactor(1, 1)
        _b外层.addWidget(_b分栏, stretch=1)

        self._b状态标签 = QLabel('正在读取 ios info …')
        _b外层.addWidget(self._b状态标签)

    # ------------------------------------------------------------------
    def f加载信息(self):
        self._b状态标签.setText('正在读取 ios info …')
        self._b桥.f执行(self._bios工具.f获取设备信息, self._budid)

    def f加载完成时(self, _b结果):
        if isinstance(_b结果, Exception):
            self._b状态标签.setText(f'读取失败：{_b结果}')
            return
        if not isinstance(_b结果, dict):
            self._b状态标签.setText('读取结果不是预期格式')
            return
        self._b原始信息 = _b结果
        _b设备名 = self._f探测(_b结果, ('DeviceName',)) or '未知设备'
        _b版本 = self._f探测(_b结果, ('ProductVersion',))
        self.setWindowTitle(f'iOS 设备信息 - {_b设备名}' + (f'（iOS {_b版本}）' if _b版本 else ''))
        # 中文映射视图
        _b中文行 = [f'<h3>{_b设备名}</h3>']
        for _b中文, _b键组 in _b字段映射:
            _b值 = self._f探测(_b结果, _b键组)
            if _b值 not in (None, ''):
                _b中文行.append(f'<p><b>{_b中文}：</b>{_b值}</p>')
        self._b中文框.setHtml(
            '<html><body style="font-size:13px;">' + ''.join(_b中文行) + '</body></html>')
        # 原始视图
        self._b原始框.setPlainText(json.dumps(_b结果, ensure_ascii=False, indent=2))
        self._b状态标签.setText('读取成功')

    # ------------------------------------------------------------------
    @staticmethod
    def _f探测(_b字典, _b键组):
        """在字典第一/二层查找任一候选键的值（info 输出可能嵌套）。"""
        for _b键 in _b键组:
            if _b键 in _b字典 and _b字典[_b键] not in (None, ''):
                return _b字典[_b键]
        for _b值 in _b字典.values():
            if isinstance(_b值, dict):
                for _b键 in _b键组:
                    if _b键 in _b值 and _b值[_b键] not in (None, ''):
                        return _b值[_b键]
        return None

    def f复制JSON(self):
        if self._b原始信息:
            QApplication.clipboard().setText(
                json.dumps(self._b原始信息, ensure_ascii=False, indent=2))
            self._b状态标签.setText('原始 JSON 已复制到剪贴板')
