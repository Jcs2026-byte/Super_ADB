# -*- coding: utf-8 -*-
"""
主入口 Mixin：iOS 调试（cIos调试Mixin）
======================================
Ios调试模块 页（tab_3）全部信号连接与业务槽，混入 主窗口：
    - 刷新 iOS 设备列表 / 设备下拉框
    - 环境自检 / 设备信息 / 截图 / 崩溃报告 / 日志（抓取 + 跟随）
    - 电池 / 磁盘 / 进程 / 应用列表 / CPU内存采样
    - 应用 启停 / 安装IPA / 卸载 / 信息
    - 隧道 / 开发者模式 / 挂载镜像

约定（新建代码遵循 c/f/b 前缀 + 中文命名）：
    类名 c 前缀、方法 f 前缀、变量 b 前缀。
后台耗时命令复用主窗口线程池（self.pool + 命令工作器），与 Android 侧一致。
"""
import json
import os

from PySide6.QtCore import QMetaObject, Qt, Q_ARG
from PySide6.QtWidgets import QFileDialog, QMessageBox

from 工具.Ios调试模块.goIos桥接 import (
    cIos设备操作, f安装指引,
)


class cIos调试Mixin:
    """Ios调试模块 控制器（新建代码：c 类 / f 方法 / b 变量 前缀）。"""

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def f初始化Ios调试模块(self):
        """主窗口 __init__ 中调用：创建 iOS 工具、连接页内控件信号。"""
        self.ios = cIos设备操作(b日志回调=self.fIos日志)
        self._bios已自动刷新 = False
        self._bios自检窗口 = None
        self._bios截图窗口 = None
        self._bios崩溃窗口 = None
        self._bios日志窗口 = None
        self._bios信息窗口 = None
        self._bios页索引 = self.tabWidget.indexOf(self.tab_3)

        # 设备栏
        self.btnIosRefresh.clicked.connect(self.f刷新Ios设备)
        self.iosDeviceCombo.currentIndexChanged.connect(self._fIos设备切换)
        # 调试通道
        self.btnIosEnvCheck.clicked.connect(self.f打开环境自检)
        self.btnIosVersion.clicked.connect(self.f打开设备信息)
        self.btnIosTunnel.clicked.connect(self.f管理隧道)
        self.btnIosDevMode.clicked.connect(self.f管理开发者模式)
        self.btnIosImage.clicked.connect(self.f挂载镜像)
        # 系统操作
        self.btnIosDetail.clicked.connect(self.f输出原始信息)
        self.btnIosSysmon.clicked.connect(self.f采样系统监控)
        self.btnIosBattery.clicked.connect(self.f读取电池)
        self.btnIosScreenshot.clicked.connect(self.f打开截图)
        self.btnIosCrash.clicked.connect(self.f打开崩溃报告)
        self.btnIosLog.clicked.connect(self.f抓取日志)
        self.btnIosDisk.clicked.connect(self.f读取磁盘)
        self.btnIosProcess.clicked.connect(self.f读取进程)
        self.btnIosApps.clicked.connect(self.f读取应用列表)
        # 应用操作
        self.btnIosLaunch.clicked.connect(self.f启动应用)
        self.btnIosStop.clicked.connect(self.f停止应用)
        self.btnIosAppInfo.clicked.connect(self.f查询应用信息)
        self.btnIosInstall.clicked.connect(self.f安装IPA)
        self.btnIosUninstall.clicked.connect(self.f卸载应用)
        self.btnIosLogFollow.clicked.connect(self.f打开日志跟随)
        # 输出区
        self.btnIosClear.clicked.connect(self.iosOutput.clear)
        self.btnIosCopy.clicked.connect(self.fIos复制输出)
        # 切到 iOS 页且尚未刷新时自动刷一次
        self.tabWidget.currentChanged.connect(self._fIos页切换时)

    # ------------------------------------------------------------------
    # iOS 页联动 / 输出
    # ------------------------------------------------------------------
    def _fIos页切换时(self, _b索引):
        if _b索引 == self._bios页索引 and not self._bios已自动刷新:
            self._bios已自动刷新 = True
            self.f刷新Ios设备()

    def _fIos设备切换(self, *_):
        """iOS 设备切换时无额外联动（iOS 通道独立）。"""

    def f当前IosUdID(self):
        """当前选中的 iOS 设备 UDID；无设备返回空串并提示。"""
        _b索引 = self.iosDeviceCombo.currentIndex()
        if _b索引 < 0:
            self.fIos日志('请先刷新并选择一台 iOS 设备')
            return ''
        return str(self.iosDeviceCombo.itemData(_b索引) or '')

    def fIos日志(self, _b文本):
        """向 iOS 输出区追加带配色日志（线程安全，与 Android 日志同机制）。"""
        _b现在 = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
        try:
            _bhtml = self._格式化日志html(str(_b文本), _b现在)
        except Exception:
            _bhtml = str(_b文本)
        if not _bhtml:
            return
        QMetaObject.invokeMethod(
            self.iosOutput, 'append',
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, _bhtml),
        )

    def fIos复制输出(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.iosOutput.toPlainText())
        self.fIos日志('已复制 iOS 输出区内容')

    # ------------------------------------------------------------------
    # 设备列表
    # ------------------------------------------------------------------
    def f刷新Ios设备(self):
        """刷新 iOS 设备下拉框（后台扫描，二进制缺失给出安装指引）。"""
        if not self.ios.f可用():
            self.设置状态('未找到 go-ios 二进制，请先安装（可点「环境自检」看指引）', ok=False)
            self.fIos日志(f'警告: {f安装指引()}')
            self.iosDeviceCombo.clear()
            return
        self.设置状态('正在扫描 iOS 设备…')
        self._fIos异步执行(self.ios.f获取设备列表, self._fIos设备列表完成时)

    def _fIos设备列表完成时(self, _b设备列表):
        if not isinstance(_b设备列表, list):
            self.设置状态('iOS 设备扫描结果异常', ok=False)
            return
        _b在线 = [_b设备 for _b设备 in _b设备列表 if isinstance(_b设备, dict)]
        _b原选择 = self.f当前IosUdID()
        self.iosDeviceCombo.blockSignals(True)
        self.iosDeviceCombo.clear()
        for _b设备 in _b在线:
            _budid = str(_b设备.get('udid') or _b设备.get('UDID') or '').strip()
            if not _budid:
                continue
            _b标签 = self._f格式化Ios设备标签(_b设备, _budid)
            self.iosDeviceCombo.addItem(_b标签, _budid)
        _b索引 = self.iosDeviceCombo.findData(_b原选择) if _b原选择 else -1
        if _b索引 >= 0:
            self.iosDeviceCombo.setCurrentIndex(_b索引)
        self.iosDeviceCombo.blockSignals(False)
        self.设置状态(f'发现 {len(_b在线)} 台 iOS 设备', ok=len(_b在线) > 0)
        if not _b在线:
            self.fIos日志('提示: 未发现 iOS 设备。数据线连接并信任此电脑后点「刷新设备列表」；'
                          'iOS 17+ 需先建隧道（可先做「环境自检」）')

    @staticmethod
    def _f格式化Ios设备标签(_b设备, _budid) -> str:
        _b名称 = (_b设备.get('name') or _b设备.get('DeviceName')
                  or _b设备.get('deviceName') or '')
        _b系统 = _b设备.get('ProductVersion') or _b设备.get('productVersion') or ''
        _b短udid = _budid if len(_budid) <= 12 else (_budid[:8] + '…')
        _b标签 = f'{_b名称}（{_b系统}）' if (_b名称 and _b系统) else (_b名称 or _b短udid)
        return f'{_b标签}  [{_b短udid}]'

    # ------------------------------------------------------------------
    # 后台执行骨架
    # ------------------------------------------------------------------
    def _fIos异步执行(self, _b函数, _b完成槽, *_b参数):
        """把同步函数丢线程池；成功→完成槽(result)；失败→日志+状态。"""
        from 项目启动入口.Super_ADB_主入口 import 命令工作器
        _b工作器 = 命令工作器(_b函数, *_b参数)

        def _f结果返回(_b结果):
            if _b完成槽 is not None:
                _b完成槽(_b结果)

        def _f出错(_b错误):
            self.fIos日志(f'错误: {_b错误}')
            self.设置状态(str(_b错误), ok=False)

        _b工作器.signals.result.connect(_f结果返回)
        _b工作器.signals.error.connect(_f出错)
        _b工作器.signals.finished.connect(lambda: self._丢弃工作器(_b工作器))
        self._live_workers.append(_b工作器)
        self.pool.start(_b工作器)

    def _fIos需要设备(self) -> bool:
        """设备不存在时给出提示并返回 False。"""
        if not self.ios.f可用():
            self.fIos日志(f'错误: {f安装指引()}')
            return False
        if not self.f当前IosUdID():
            return False
        return True

    # ------------------------------------------------------------------
    # 调试通道
    # ------------------------------------------------------------------
    def f打开环境自检(self):
        from 对话框.Ios调试模块.iOS环境自检对话框 import cIos环境自检对话框
        _b窗口 = self._bios自检窗口
        if _b窗口 is not None:
            try:
                if _b窗口.isVisible():
                    _b窗口.raise_()
                    _b窗口.activateWindow()
                    return
            except RuntimeError:
                self._bios自检窗口 = None
        _b窗口 = cIos环境自检对话框(self.ios, self)
        _b窗口.destroyed.connect(
            lambda _b对象=None, _b自身=self: _b自身._fIos清空窗口引用('_bios自检窗口', _b对象))
        self._bios自检窗口 = _b窗口
        _b窗口.show()

    def f打开设备信息(self):
        if not self._fIos需要设备():
            return
        from 对话框.Ios调试模块.iOS设备信息对话框 import cIos设备信息对话框
        _b窗口 = self._bios信息窗口
        if _b窗口 is not None:
            try:
                if _b窗口.isVisible():
                    _b窗口.raise_()
                    _b窗口.activateWindow()
                    return
            except RuntimeError:
                self._bios信息窗口 = None
        _b窗口 = cIos设备信息对话框(self.ios, self.f当前IosUdID(), self)
        _b窗口.destroyed.connect(
            lambda _b对象=None, _b自身=self: _b自身._fIos清空窗口引用('_bios信息窗口', _b对象))
        self._bios信息窗口 = _b窗口
        _b窗口.show()

    def f管理隧道(self):
        """查看隧道；无隧道时询问是否启动（Windows 需管理员）。"""
        if not self.ios.f可用():
            self.fIos日志(f'错误: {f安装指引()}')
            return
        try:
            _b隧道 = self.ios.f检查隧道()
        except Exception as _b异常:
            self.fIos日志(f'错误: 隧道查询失败：{_b异常}')
            return
        if _b隧道:
            self.fIos日志(f'当前活动隧道 {len(_b隧道)} 条：')
            for _b条 in _b隧道[:10]:
                self.fIos日志(str(_b条))
            return
        _b询问 = QMessageBox.question(
            self, '启动隧道',
            '当前没有活动隧道。\n'
            'iOS 17+ 设备必须先建立隧道才能调试。\n\n'
            '是否现在启动？（Windows 需要以管理员身份运行本工具，'
            '且已安装 wintun.dll 到 C:/Windows/system32）',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if _b询问 == QMessageBox.StandardButton.Yes:
            self.设置状态('正在启动隧道…')
            self._fIos异步执行(
                self.ios.f启动隧道, lambda _b结果: self.fIos日志(str(_b结果)))

    def f管理开发者模式(self):
        if not self._fIos需要设备():
            return
        try:
            _b状态 = self.ios.f读取开发者模式(self.f当前IosUdID())
        except Exception as _b异常:
            _b状态 = ''
            self.fIos日志(f'错误: 查询开发者模式失败：{_b异常}')
        self.fIos日志(f'开发者模式状态: {_b状态 or "未知"}')
        _b小写 = (_b状态 or '').lower()
        if 'enable' in _b小写 or 'on' in _b小写 and 'unknown' not in _b小写:
            return
        _b询问 = QMessageBox.question(
            self, '开启开发者模式',
            '设备未开启开发者模式。\n'
            '是否尝试远程开启？开启后设备会提示重启以生效。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if _b询问 == QMessageBox.StandardButton.Yes:
            self.设置状态('正在开启开发者模式…')
            self._fIos异步执行(
                self.ios.f开启开发者模式,
                lambda _b结果: self.fIos日志(str(_b结果)))

    def f挂载镜像(self):
        """自动下载并挂载开发者镜像（耗时较长，放线程池）。"""
        if not self._fIos需要设备():
            return
        self.设置状态('正在挂载开发者镜像（首次需联网下载，较慢）…')
        self._fIos异步执行(
            self.ios.f挂载开发者镜像, self._fIos结果输出为日志)

    # ------------------------------------------------------------------
    # 系统操作
    # ------------------------------------------------------------------
    def f输出原始信息(self):
        """详情：输出 go-ios version + ios info 原始 JSON 到输出区。"""
        if not self._fIos需要设备():
            return
        def _f取原始():
            _budid = self.f当前IosUdID()
            _b版本 = self.ios.f获取版本()
            _b信息 = self.ios.f获取设备信息(_budid)
            return f'$ ios version\n{_b版本}\n\n$ ios info\n' + json.dumps(
                _b信息, ensure_ascii=False, indent=2)
        self._fIos异步执行(_f取原始, self._fIos结果输出为日志)

    def f采样系统监控(self):
        if not self._fIos需要设备():
            return
        self.设置状态('正在采样 sysmontap（约 5 秒）…')
        self._fIos异步执行(self._fIos采样一帧, self.fIos日志)

    def _fIos采样一帧(self):
        """后台：采一帧 CPU/内存并格式化为文本。"""
        _budid = self.f当前IosUdID()
        _b帧 = self.ios.f采样系统监控(_budid, _b时长秒=5.0)
        _b行 = ['采样结果（字段以 go-ios 实际 JSON 为准）:']
        for _b键, _b值 in _b帧.items():
            if _b键 == 'per_core' and isinstance(_b值, dict):
                _b核 = ', '.join(f'核{i}:{v}%' for i, v in _b值.items())
                _b行.append(f'每核占用: {_b核}')
            else:
                _b行.append(f'{_b键}: {_b值}')
        return '\n'.join(_b行)

    def f读取电池(self):
        if not self._fIos需要设备():
            return
        self._fIos异步执行(
            self.ios.f读取电池, self._fIos结果输出为日志)

    def f读取磁盘(self):
        if not self._fIos需要设备():
            return
        self._fIos异步执行(
            self.ios.f读取磁盘, self._fIos结果输出为日志)

    def f读取进程(self):
        if not self._fIos需要设备():
            return
        def _f取进程():
            _b进程 = self.ios.f读取进程(self.f当前IosUdID())
            if not _b进程:
                return '设备上未取到进程列表'
            _b行 = [f'共 {len(_b进程)} 个进程']
            for _b进程项 in _b进程:
                _b名字 = _b进程项.get('name') or _b进程项.get('Name') or ''
                _bpid = _b进程项.get('pid') or _b进程项.get('Pid') or ''
                _b行.append(f'{_bpid}\t{_b名字}')
            return '\n'.join(_b行)
        self._fIos异步执行(_f取进程, self.fIos日志)

    def f读取应用列表(self):
        if not self._fIos需要设备():
            return
        def _f取应用():
            _b应用 = self.ios.f获取应用列表(self.f当前IosUdID(), _b只要简表=True)
            if not _b应用:
                return '设备上未取到应用列表'
            _b行 = [f'共 {len(_b应用)} 个应用（前 200 条）']
            for _b应用项 in _b应用[:200]:
                if not isinstance(_b应用项, dict):
                    _b行.append(str(_b应用项))
                    continue
                _bid = (_b应用项.get('bundleID') or _b应用项.get('BundleIdentifier')
                        or _b应用项.get('CFBundleIdentifier') or _b应用项.get('id') or '?')
                _b名字 = (_b应用项.get('name') or _b应用项.get('Name')
                         or _b应用项.get('bundleName') or '')
                _b版本 = _b应用项.get('version') or _b应用项.get('Version') or ''
                _b行.append(f'{_bid}\t{_b名字}\t{_b版本}')
            return '\n'.join(_b行)
        self._fIos异步执行(_f取应用, self.fIos日志)

    def f抓取日志(self):
        if not self._fIos需要设备():
            return
        self.设置状态('正在抓取 syslog（截取约 6 秒）…')
        self._fIos异步执行(self._fIos抓一段日志, self.fIos日志)

    def _fIos抓一段日志(self):
        return self.ios.f抓取日志(self.f当前IosUdID(), _b时长秒=6.0, _b最大行=200) \
            or '（抓取区间内无日志输出）'

    # ------------------------------------------------------------------
    # 应用操作
    # ------------------------------------------------------------------
    def _fIos取Bundle(self) -> str:
        _bid = self.iosBundleInput.text().strip()
        if not _bid:
            self.fIos日志('请先在 Bundle ID 输入框填写应用标识（如 com.apple.mobilesafari）')
        return _bid

    def f启动应用(self):
        _bid = self._fIos取Bundle()
        if not _bid or not self._fIos需要设备():
            return
        self.设置状态(f'正在启动 {_bid} …')
        self._fIos异步执行(self.ios.f启动应用, self._fIos结果输出为日志,
                           self.f当前IosUdID(), _bid)

    def f停止应用(self):
        _bid = self._fIos取Bundle()
        if not _bid or not self._fIos需要设备():
            return
        self.设置状态(f'正在停止 {_bid} …')
        self._fIos异步执行(self.ios.f停止应用, self._fIos结果输出为日志,
                           self.f当前IosUdID(), _bid)

    def f卸载应用(self):
        _bid = self._fIos取Bundle()
        if not _bid or not self._fIos需要设备():
            return
        _b确认 = QMessageBox.question(
            self, '确认卸载', f'确认从设备卸载 {_bid} ？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if _b确认 != QMessageBox.StandardButton.Yes:
            return
        self.设置状态(f'正在卸载 {_bid} …')
        self._fIos异步执行(self.ios.f卸载应用, self._fIos结果输出为日志,
                           self.f当前IosUdID(), _bid)

    def f安装IPA(self):
        if not self._fIos需要设备():
            return
        _b路径, _ = QFileDialog.getOpenFileName(
            self, '选择 IPA 文件', '', 'IPA 安装包 (*.ipa);;所有文件 (*)')
        if not _b路径:
            return
        self.设置状态('正在安装 IPA（大包较慢）…')
        self._fIos异步执行(self.ios.f安装IPA, self._fIos结果输出为日志,
                           self.f当前IosUdID(), _b路径)

    def f查询应用信息(self):
        _bid = self._fIos取Bundle()
        if not _bid or not self._fIos需要设备():
            return
        def _f查信息():
            _b应用 = self.ios.f获取应用列表(self.f当前IosUdID(), _b只要简表=False)
            for _b项 in _b应用 if isinstance(_b应用, list) else []:
                if not isinstance(_b项, dict):
                    continue
                _b候选 = (_b项.get('bundleID') or _b项.get('BundleIdentifier')
                          or _b项.get('CFBundleIdentifier') or _b项.get('id') or '')
                if str(_b候选) == _bid:
                    return json.dumps(_b项, ensure_ascii=False, indent=2)
            return f'设备上未找到 {_bid}（请先「应用列表」核对 Bundle ID）'
        self._fIos异步执行(_f查信息, self.fIos日志)

    # ------------------------------------------------------------------
    # 对话框类功能
    # ------------------------------------------------------------------
    def f打开截图(self):
        if not self._fIos需要设备():
            return
        from 对话框.Ios调试模块.iOS截图预览 import cIos截图预览对话框
        _b窗口 = self._bios截图窗口
        if _b窗口 is not None:
            try:
                if _b窗口.isVisible():
                    _b窗口.raise_()
                    _b窗口.activateWindow()
                    return
            except RuntimeError:
                self._bios截图窗口 = None
        _b窗口 = cIos截图预览对话框(self.ios, self.f当前IosUdID(), self)
        _b窗口.destroyed.connect(
            lambda _b对象=None, _b自身=self: _b自身._fIos清空窗口引用('_bios截图窗口', _b对象))
        self._bios截图窗口 = _b窗口
        _b窗口.show()

    def f打开崩溃报告(self):
        if not self._fIos需要设备():
            return
        from 对话框.Ios调试模块.iOS崩溃报告对话框 import cIos崩溃报告对话框
        _b窗口 = self._bios崩溃窗口
        if _b窗口 is not None:
            try:
                if _b窗口.isVisible():
                    _b窗口.raise_()
                    _b窗口.activateWindow()
                    return
            except RuntimeError:
                self._bios崩溃窗口 = None
        _b窗口 = cIos崩溃报告对话框(self.ios, self.f当前IosUdID(), self)
        _b窗口.destroyed.connect(
            lambda _b对象=None, _b自身=self: _b自身._fIos清空窗口引用('_bios崩溃窗口', _b对象))
        self._bios崩溃窗口 = _b窗口
        _b窗口.show()

    def f打开日志跟随(self):
        if not self._fIos需要设备():
            return
        from 对话框.Ios调试模块.iOS日志对话框 import cIos日志跟随对话框
        _b窗口 = self._bios日志窗口
        if _b窗口 is not None:
            try:
                if _b窗口.isVisible():
                    _b窗口.raise_()
                    _b窗口.activateWindow()
                    return
            except RuntimeError:
                self._bios日志窗口 = None
        _b窗口 = cIos日志跟随对话框(self.ios, self.f当前IosUdID(), self)
        _b窗口.destroyed.connect(
            lambda _b对象=None, _b自身=self: _b自身._fIos清空窗口引用('_bios日志窗口', _b对象))
        self._bios日志窗口 = _b窗口
        _b窗口.show()

    # ------------------------------------------------------------------
    # 公共小工具
    # ------------------------------------------------------------------
    def _fIos结果输出为日志(self, _b结果):
        """把 worker 结果打印到 iOS 输出区（dict/list 美化，异常标红）。"""
        if isinstance(_b结果, Exception):
            self.fIos日志(f'错误: {_b结果}')
            self.设置状态(str(_b结果), ok=False)
            return
        if _b结果 is None:
            self.fIos日志('（无输出）')
            return
        if isinstance(_b结果, dict):
            self.fIos日志(json.dumps(_b结果, ensure_ascii=False, indent=2))
            return
        if isinstance(_b结果, (list, tuple)):
            _b行 = [f'共 {len(_b结果)} 条'] + [str(x) for x in _b结果[:300]]
            self.fIos日志('\n'.join(_b行))
            return
        self.fIos日志(str(_b结果))

    def _fIos清空窗口引用(self, _b属性名, _b对象):
        """弹窗 destroyed 后清引用（带对象身份判断，防止误清新窗口）。"""
        if getattr(self, _b属性名, None) is _b对象:
            setattr(self, _b属性名, None)
