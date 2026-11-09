"""历史连接设备对话框：展示历史连接过的设备，支持重连和删除。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget,
    QScrollArea, QFrame, QSizePolicy
)
from 工具.android调试工具.ADB工具 import 加载json配置, 保存json配置

# 配置文件名
_HISTORY_CFG = '历史连接设备.json'


def _load_history():
    """加载历史连接设备列表（包含 WiFi 配对过的设备）。"""
    devices = []
    # 1. 加载自己的历史记录
    history = 加载json配置(_HISTORY_CFG)
    if isinstance(history, list):
        devices = history
    # 2. 加载 WiFi 配对过的设备，合并进来
    try:
        paired = 加载json配置('WiFi配对设备.json')
        if isinstance(paired, list):
            # 按 IP 去重，配对的设备如果不在历史里就加进去
            existing_ips = {d.get('ip') for d in devices}
            for p in paired:
                ip = p.get('ip', '')
                if ip and ip not in existing_ips:
                    devices.append({
                        'ip': ip,
                        'port': p.get('debug_port', 5555),
                        'model': p.get('model', '')
                    })
    except Exception:
        pass
    return devices


def _save_history(devices):
    """保存历史连接设备列表。"""
    保存json配置(_HISTORY_CFG, devices)


def 添加历史设备(ip, port, model=''):
    """连接成功后调用，添加设备到历史记录。"""
    devices = _load_history()
    serial = f"{ip}:{port}"
    # 先找到同 IP 的旧记录，保留原来的 system_version 和 is_single_channel 字段
    old_entry = None
    for d in devices:
        if d.get('ip') == ip:
            old_entry = d
            break
    # 去掉已有的同IP记录
    devices = [d for d in devices if d.get('ip') != ip]
    # 插到最前面，保留旧记录里的字段
    new_entry = {
        'ip': ip,
        'port': port,
        'model': model
    }
    # 保留旧记录里的字段
    if old_entry:
        if old_entry.get('system_version'):
            new_entry['system_version'] = old_entry.get('system_version')
        if old_entry.get('is_single_channel') is not None:
            new_entry['is_single_channel'] = old_entry.get('is_single_channel')
    devices.insert(0, new_entry)
    # 最多保留 20 条
    devices = devices[:20]
    _save_history(devices)


class 历史连接设备对话框(QDialog):
    """历史连接设备对话框。"""

    def __init__(self, adb, on_reconnect=None, parent=None, theme_id=None):
        super().__init__(parent)
        self.adb = adb
        self._on_reconnect = on_reconnect
        self._devices = []
        self._theme_id = theme_id or 'default'
        self.setWindowTitle("历史连接设备")
        self.setMinimumWidth(680)
        self.setMinimumHeight(400)
        from 项目UI.界面样式 import get_stylesheet
        from 项目UI.弹窗样式 import _create_popup_card
        self.setStyleSheet(get_stylesheet(self._theme_id))
        # 内层亮边卡片
        self.card, _ = _create_popup_card(self, self._theme_id)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        root = QVBoxLayout(self.card)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("📜 历史连接过的设备")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        hint = QLabel("⚠️ 单通道设备仅允许一个 ADB 连接，自研与官方不可同时保持")
        hint.setStyleSheet("font-size: 11px; color: #888;")
        hint.setWordWrap(True)
        title_row.addWidget(hint)
        self._title_row = title_row
        root.addLayout(title_row)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(4)

        # 设备列表放进竖向滚动区：条目多时出现滚动条，弹窗高度不再被撑长
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }'
        )
        list_widget = QWidget()
        list_widget.setObjectName('historyListHost')
        list_widget.setStyleSheet(
            'QWidget#historyListHost { background: transparent; }'
        )
        self._list_layout.setContentsMargins(0, 0, 8, 0)  # 右侧留出滚动条空间
        list_widget.setLayout(self._list_layout)
        self._scroll.setWidget(list_widget)
        root.addWidget(self._scroll, 1)

        self._apply_max_height()

    def _apply_max_height(self):
        """限制弹窗最大高度为屏幕可用高度的 72%，超出部分交给滚动区。"""
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry().height() if screen else 900
        except Exception:
            avail = 900
        self._max_height = max(int(avail * 0.72), self.minimumHeight())
        self.setMaximumHeight(self._max_height)

    def _fit_height(self):
        """按条目数调整弹窗高度：条目少时贴合内容，条目多时封顶并出现滚动条。"""
        max_h = getattr(self, '_max_height', 0)
        host = self._scroll.widget() if hasattr(self, '_scroll') else None
        if not max_h or host is None:
            return
        # 弹窗除列表外的固定开销：内外边距 + 标题行 + 间距
        root = self.card.layout()
        inner = root.contentsMargins()
        outer = self.layout().contentsMargins()
        chrome = (inner.top() + inner.bottom() + outer.top() + outer.bottom()
                  + root.spacing() + self._title_row.sizeHint().height()
                  + self._scroll.frameWidth() * 2)
        want = host.sizeHint().height() + chrome
        self.resize(self.width(), min(max(want, self.minimumHeight()), max_h))

    def _refresh_list(self):
        # 清空旧列表
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._devices = _load_history()
        if not self._devices:
            lbl = QLabel("暂无历史连接记录")
            lbl.setStyleSheet("color: #888;")
            self._list_layout.addWidget(lbl)
            self._list_layout.addStretch()
            self._fit_height()
            return

        for entry in self._devices:
            ip = entry.get('ip', '')
            port = entry.get('port', 5555)
            model = entry.get('model', '')
            system_version = entry.get('system_version', '')
            # 从设备能力配置里查询是不是单通道
            is_single_channel = False
            try:
                from 工具.配置.设备能力 import 是否单通道
                result = 是否单通道(model, system_version)
                if result is True:
                    is_single_channel = True
            except Exception:
                pass
            row = QHBoxLayout()

            # 显示设备名 + 单通道标记 + 系统版本 + IP
            label_text = ""
            if model:
                label_text += f"{model}"
            if is_single_channel:
                label_text += " 🔒单通道"
            if system_version:
                label_text += f" [Android {system_version}]"
            label_text += f"  [{ip}:{port}]"
            label = QLabel(label_text)
            # 名称过长时截断显示，避免把「重连/删除」按钮挤出可视区
            label.setToolTip(label_text)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
            row.addWidget(label, 1)

            # 重连按钮
            btn_re = QPushButton("重连")
            btn_re.setMaximumWidth(60)
            btn_re.clicked.connect(lambda _checked=False, e=entry: self._reconnect(e))
            row.addWidget(btn_re)

            # 删除按钮
            btn_del = QPushButton("删除")
            btn_del.setMaximumWidth(60)
            btn_del.clicked.connect(lambda _checked=False, e=entry: self._delete(e))
            row.addWidget(btn_del)

            container = QWidget()
            container.setLayout(row)
            self._list_layout.addWidget(container)

        # 末尾留白：条目较少时向上对齐，超出时由滚动区接管
        self._list_layout.addStretch()
        self._fit_height()

    def _reconnect(self, entry):
        """重连设备。"""
        ip = entry.get('ip', '')
        port = entry.get('port', 5555)
        if self._on_reconnect:
            self._on_reconnect(ip, port)
        self.accept()

    def _delete(self, entry):
        """删除历史记录，同时删除 WiFi 配对里的同 IP 记录。"""
        ip = entry.get('ip', '')
        # 删除自己的历史记录
        self._devices = [d for d in self._devices if d.get('ip') != ip]
        _save_history(self._devices)
        # 同时删除 WiFi 配对里的同 IP 记录
        try:
            paired = 加载json配置('WiFi配对设备.json')
            if isinstance(paired, list):
                paired = [p for p in paired if p.get('ip') != ip]
                保存json配置('WiFi配对设备.json', paired)
        except Exception:
            pass
        self._refresh_list()
