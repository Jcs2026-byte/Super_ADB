# -*- coding: utf-8 -*-
"""
pymobiledevice3 桥接（Super_Debug_Win/工具/Ios调试模块/pymd3桥接.py）
===================================================================
以 GPL-3.0 的 pymobiledevice3（纯 Python CLI）作为 iOS 后端，通过
「子进程调用 + JSON 解析」接入，与 Android 侧「Python UI + adb 外部二进制」形态一致，
也与本工具此前 go-ios 后端的调用方式同构（外部进程、arm's length，不与其代码链接）。

对外主类：cIos设备操作（与旧 goIos桥接 同名同签名，上层无需改调用）
    - 入口自动发现（环境变量 / PATH / 解释器 Scripts / 兜底 python -m pymobiledevice3）
    - 统一超时执行、中文错误、JSON 容错
    - 覆盖日常链路：设备 / 信息 / 应用 / 截图 / 崩溃 / 日志 / 监控 / 隧道 / 开发者模式 / 镜像

环境自检：f执行环境自检() 逐项返回 {名称, 状态, 信息, 指引}，
供「iOS 环境自检面板」红绿灯展示。

命名规范：类名前缀 c、方法名前缀 f、变量名前缀 b；私有方法 _f、私有变量 _b。

模拟模式（无真机联调）：
    设置环境变量 SUPER_ADB_IOS_MOCK=1 后，桥接以
    「python 工具/Ios调试模块/pymd3模拟器.py <args…>」代替真实 pymobiledevice3 运行。
    取消该环境变量即回到真实后端，模拟器不参与任何生产路径。

已知能力差异（相对 go-ios）：
    - 磁盘容量：pymobiledevice3 未提供对应子命令，f读取磁盘() 返回说明性字典（见方法注释）。
    - 隧道：iOS 17+ 由 pymobiledevice3 按需自动建立（userspace，无需 root）；
      f启动隧道() 启动的是可选的 tunneld 常驻服务，用于加速重复连接。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request

_bWIN = sys.platform.startswith('win')

# 模拟器脚本名（与桥接同目录）
_b模拟器文件名 = 'pymd3模拟器.py'

# tunneld 默认监听地址（与 pymobiledevice3.tunneld.api.TUNNELD_DEFAULT_ADDRESS 一致）
_b隧道默认地址 = ('127.0.0.1', 49151)


class cIos错误(Exception):
    """iOS 桥接统一异常：消息面向用户、可读。"""


def _f是否启用模拟() -> bool:
    """是否以 pymd3模拟器.py 代替真实 pymobiledevice3（SUPER_ADB_IOS_MOCK=1）。"""
    _b值 = os.environ.get('SUPER_ADB_IOS_MOCK', '').strip().lower()
    return _b值 in ('1', 'true', 'yes', 'on')


def _f查找模拟器() -> str:
    """模拟模式：返回与桥接同目录的 pymd3模拟器.py 绝对路径（缺失返回空）。"""
    if not _f是否启用模拟():
        return ''
    _b脚本 = os.path.join(os.path.dirname(os.path.abspath(__file__)), _b模拟器文件名)
    return _b脚本 if os.path.isfile(_b脚本) else ''


def f查找Pmd3前缀() -> list:
    """探测 pymobiledevice3 的调用前缀，返回 list（可直接 + 子命令拼成 argv）。

    查找顺序：
        0. SUPER_ADB_IOS_MOCK=1 时：[sys.executable, pymd3模拟器.py]
        1. 环境变量 SUPER_ADB_PMD3_BIN（指向可执行文件时直接用；
           指向 .py 时前置 sys.executable）
        2. PATH 中的 pymobiledevice3 / .exe / .cmd
        3. 当前解释器同级 Scripts/pymobiledevice3.exe（Windows 常规安装位）
        4. Unix 常见位置 /usr/local/bin、~/.local/bin
        5. 兜底 [sys.executable, '-m', 'pymobiledevice3']（只要包装到环境里就能跑）
    模拟模式开启但脚本缺失时返回空 list——用户显式要求模拟，缺脚本即打包缺失，
    不回落到真实后端，避免静默跑错后端。
    """
    _b模拟器 = _f查找模拟器()
    if _b模拟器:
        return [sys.executable, _b模拟器]
    if _f是否启用模拟():
        return []

    _b环境指定 = os.environ.get('SUPER_ADB_PMD3_BIN', '').strip()
    if _b环境指定:
        if _b环境指定.lower().endswith('.py'):
            return [sys.executable, _b环境指定]
        return [_b环境指定]

    for _b名 in ('pymobiledevice3', 'pymobiledevice3.exe', 'pymobiledevice3.cmd'):
        _b命中 = shutil.which(_b名)
        if _b命中:
            return [_b命中]

    _b解释器目录 = os.path.dirname(sys.executable or '')
    _b候选 = []
    if _b解释器目录:
        _b候选.append(os.path.join(_b解释器目录, 'Scripts', 'pymobiledevice3.exe'))
        _b候选.append(os.path.join(_b解释器目录, 'pymobiledevice3'))
    _b候选 += [
        '/usr/local/bin/pymobiledevice3',
        os.path.expanduser('~/.local/bin/pymobiledevice3'),
    ]
    for _b路径 in _b候选:
        if _b路径 and os.path.isfile(_b路径):
            return [_b路径]
    return [sys.executable, '-m', 'pymobiledevice3']


def f前缀说明(_b前缀) -> str:
    """把调用前缀格式化为人类可读文本（日志/环境自检展示用）。"""
    if not _b前缀:
        return '（空）'
    if len(_b前缀) >= 2 and _b前缀[-2:] == ['-m', 'pymobiledevice3']:
        return f'{_b前缀[0]} -m pymobiledevice3'
    return ' '.join(_b前缀)


def f安装指引() -> str:
    """模拟模式缺脚本 / 后端缺失时，给用户的可执行修复指引。"""
    if _f是否启用模拟():
        return (f'模拟模式已开启（SUPER_ADB_IOS_MOCK=1），但未找到模拟器脚本 '
                f'工具/Ios调试模块/{_b模拟器文件名}。\n'
                f'请确认该文件随工程存在；或取消 SUPER_ADB_IOS_MOCK 环境变量回到真实后端。')
    _b行 = [
        '未找到 pymobiledevice3。任选一种方式安装后重试：',
        '  1) pip 安装（推荐）：pip install -U pymobiledevice3',
        '  2) 指定可执行文件：设置环境变量 SUPER_ADB_PMD3_BIN 指向其绝对路径',
        '  3) 若已装但不在 PATH：确认 Python 的 Scripts 目录（Windows）'
        '或 /usr/local/bin（Linux/macOS）在系统 PATH 中',
        '',
        'Windows 注意（这是和 go-ios 的关键差异）：',
        '  pymobiledevice3 走 usbmuxd 协议（127.0.0.1:27015），',
        '  Windows 上 usbmuxd 只由 Apple Mobile Device Service 提供。',
        '  不必装完整 iTunes —— Microsoft Store 装「Apple Devices」',
        '  「Apple Music」「Apple TV」任一即可（都自带 AMD 驱动），',
        '  装完插一次 iPhone 触发驱动加载，然后：',
        '    netstat -an | findstr 27015',
        '  看到 LISTENING 即可。Linux/macOS 需 usbmuxd 守护进程在跑。',
    ]
    return '\n'.join(_b行)


def f查询隧道服务() -> list:
    """查询本机 tunneld 常驻服务上的活动隧道；服务未运行返回空列表。

    tunneld 首页返回 {udid: [隧道详情, …]}，此处摊平成
    [{udid, 地址, 端口, 详情}] 便于 UI 直接展示。
    """
    _b地址 = f'http://{_b隧道默认地址[0]}:{_b隧道默认地址[1]}'
    try:
        with urllib.request.urlopen(_b地址, timeout=2.0) as _b响应:
            _b数据 = json.loads(_b响应.read().decode('utf-8', errors='replace'))
    except Exception:
        return []
    if not isinstance(_b数据, dict):
        return []
    _b结果 = []
    for _budid, _b详情列表 in _b数据.items():
        if not isinstance(_b详情列表, list):
            _b详情列表 = [_b详情列表]
        for _b详情 in _b详情列表:
            _b条目 = {'udid': str(_budid)}
            if isinstance(_b详情, dict):
                _b条目['地址'] = _b详情.get('address') or _b详情.get('Address') or ''
                _b条目['端口'] = _b详情.get('port') or _b详情.get('Port') or ''
                _b条目['详情'] = _b详情
            _b结果.append(_b条目)
    return _b结果


class cIos设备操作:
    """pymobiledevice3 子进程桥接（c 类 / f 方法 / b 变量 前缀 + 中文命名）。

    用法：
        _b工具 = cIos设备操作(b日志回调=主窗口.日志)
        _b设备 = _b工具.f获取设备列表()
    所有方法同步执行，耗时命令请放线程池（UI 侧与 Android 命令工作器一致）。

    与 go-ios 版的关键差异：
        --udid 是子命令级选项（pymobiledevice3 apps list --udid X），
        因此 f构造命令 把 --udid 追加在子命令之后，而不是像 go-ios 那样前置。
    """

    def __init__(self, b日志回调=None):
        self._b日志回调 = b日志回调
        self._b命令前缀 = f查找Pmd3前缀()
        self._b检测锁 = threading.Lock()

    # ------------------------------------------------------------------
    # 基础能力
    # ------------------------------------------------------------------
    def f刷新命令前缀(self) -> list:
        """重新探测调用前缀（用户安装 pymobiledevice3 后调用）。"""
        with self._b检测锁:
            self._b命令前缀 = f查找Pmd3前缀()
        return self._b命令前缀

    def f可用(self) -> bool:
        """pymobiledevice3（或模拟器脚本）是否就绪。"""
        _b前缀 = self._b命令前缀
        if not _b前缀:
            return False
        if _f是否启用模拟():
            return len(_b前缀) >= 2 and os.path.isfile(_b前缀[1])
        # 兜底前缀 [python, '-m', 'pymobiledevice3']：模块能找到才算可用
        if len(_b前缀) >= 2 and _b前缀[-2:] == ['-m', 'pymobiledevice3']:
            import importlib.util
            try:
                return importlib.util.find_spec('pymobiledevice3') is not None
            except (ImportError, ValueError):
                return False
        return os.path.isfile(_b前缀[0]) or bool(shutil.which(_b前缀[0]))

    def f是否模拟模式(self) -> bool:
        """当前是否运行在 pymd3模拟器（SUPER_ADB_IOS_MOCK=1）下。"""
        return _f是否启用模拟() and bool(self._b命令前缀)

    def f日志(self, b文本):
        """透传日志回调（线程安全由调用方保证，可空）。"""
        if self._b日志回调 is not None:
            try:
                self._b日志回调(b文本)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 子进程执行层
    # ------------------------------------------------------------------
    def f构造命令(self, _budid, *_b子命令) -> list:
        """拼出完整命令行：前缀 + 子命令 + [--udid <udid>]。

        注意：pymobiledevice3 的 --udid 属于子命令级选项，必须放在子命令之后；
        udid 为空时不追加，交给 pymobiledevice3 默认取第一台设备。
        """
        _b命令 = list(self._b命令前缀)
        _b命令.extend(str(x) for x in _b子命令)
        if _budid:
            _b命令.extend(['--udid', str(_budid)])
        return _b命令

    def f运行命令(self, _b参数, _b超时秒=30.0) -> str:
        """执行并返回标准输出文本；非零返回码/异常转 cIos错误（中文信息）。"""
        if not self.f可用():
            raise cIos错误(f安装指引())
        _b显示 = ' '.join(str(x) for x in _b参数)
        self.f日志('$ ' + _b显示)
        try:
            _b结果 = subprocess.run(
                _b参数,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=_b超时秒,
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0,
            )
        except subprocess.TimeoutExpired:
            raise cIos错误(f'命令超时（>{_b超时秒:.0f}s）：{_b显示}')
        except FileNotFoundError:
            raise cIos错误(f安装指引())
        except OSError as _b异常:
            raise cIos错误(f'启动 pymobiledevice3 失败：{_b异常}')
        _b输出 = (_b结果.stdout or '').strip()
        if _b结果.returncode != 0:
            _b原因 = (_b结果.stderr or _b输出 or '未知错误').strip()
            _b首行 = _b原因.splitlines()[0] if _b原因.splitlines() else _b原因
            if len(_b首行) > 160:
                _b首行 = _b首行[:160] + '…'
            raise cIos错误(f'pymobiledevice3 命令失败（{_b结果.returncode}）：{_b首行}\n{_b显示}')
        return _b输出

    def f运行Json(self, _b参数, _b超时秒=30.0):
        """执行并把 stdout 当 JSON 解析；不是 JSON 时原样返回文本。"""
        _b文本 = self.f运行命令(_b参数, _b超时秒=_b超时秒)
        if not _b文本:
            return None
        try:
            return json.loads(_b文本)
        except json.JSONDecodeError:
            return _b文本

    # ------------------------------------------------------------------
    # 设备 / 信息
    # ------------------------------------------------------------------
    def f获取设备列表(self) -> list:
        """usbmux list → 设备数组。

        pymobiledevice3 返回 lockdown 的 short_info：
        {Identifier, DeviceClass, DeviceName, BuildVersion, ProductVersion,
         ProductType, UniqueDeviceID[, ConnectionType]}
        此处统一补出 udid / name 两个键，使上层沿用 go-ios 时期的字段读取方式。
        """
        _b数据 = self.f运行Json(self.f构造命令('', 'usbmux', 'list'), _b超时秒=30)
        if isinstance(_b数据, dict) and isinstance(_b数据.get('devices'), list):
            _b数据 = _b数据['devices']
        if not isinstance(_b数据, list):
            return []
        _b结果 = []
        for _b项 in _b数据:
            if not isinstance(_b项, dict):
                continue
            _b设备 = dict(_b项)
            _budid = str(_b设备.get('UniqueDeviceID')
                         or _b设备.get('Identifier')
                         or _b设备.get('udid') or '')
            if _budid:
                _b设备.setdefault('udid', _budid)
            _b名称 = _b设备.get('DeviceName')
            if _b名称:
                _b设备.setdefault('name', _b名称)
            _b结果.append(_b设备)
        return _b结果

    def f获取版本(self) -> str:
        """version → 人类可读版本串（pymobiledevice3 直接输出版本号纯文本）。"""
        _b文本 = self.f运行命令(self.f构造命令('', 'version'), _b超时秒=20)
        _b首行 = _b文本.strip().splitlines()[0] if _b文本.strip() else ''
        return f'版本 {_b首行}' if _b首行 else _b文本

    def f获取设备信息(self, _budid='') -> dict:
        """lockdown info → 设备信息字典（键名与 go-ios info 基本一致）。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'lockdown', 'info'), _b超时秒=60)
        return _b数据 if isinstance(_b数据, dict) else {}

    def f获取设备名称(self, _budid='') -> str:
        """快速拿设备名（info 失败时不影响调用方）。"""
        try:
            _b数据 = self.f获取设备信息(_budid)
            return str(_b数据.get('DeviceName') or '')
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # 应用操作
    # ------------------------------------------------------------------
    def f获取应用列表(self, _budid='', _b只要简表=True) -> list:
        """apps list → 应用数组。

        pymobiledevice3 返回 {bundleId: {…应用信息}} 字典；
        此处摊平为数组并补齐 bundleID / name / version，使上层沿用旧字段读取方式。
        _b只要简表=False 时额外带上 --calculate-sizes（pymobiledevice3 的"详细"等价物）。
        """
        _b参数 = self.f构造命令(_budid, 'apps', 'list')
        if not _b只要简表:
            _b参数.append('--calculate-sizes')
        _b数据 = self.f运行Json(_b参数, _b超时秒=90)
        if not isinstance(_b数据, dict):
            return []
        _b结果 = []
        for _b包名, _b信息 in _b数据.items():
            if not isinstance(_b信息, dict):
                _b信息 = {'值': _b信息}
            _b项 = dict(_b信息)
            _b项.setdefault('bundleID', _b包名)
            _b项.setdefault('name', _b信息.get('CFBundleDisplayName')
                            or _b信息.get('CFBundleName') or '')
            _b项.setdefault('version', _b信息.get('CFBundleShortVersionString')
                            or _b信息.get('CFBundleVersion') or '')
            _b结果.append(_b项)
        return _b结果

    def f启动应用(self, _budid, _bbundleId) -> str:
        """developer dvt launch <bundleId>（默认 --kill-existing）。"""
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'developer', 'dvt', 'launch', _bbundleId),
            _b超时秒=60)
        return _b文本 or '已发出启动指令'

    def f停止应用(self, _budid, _bbundleId) -> str:
        """developer dvt pkill <bundleId> --bundle。

        注意：dvt kill 只接受 PID；按包名的场景必须用 pkill --bundle。
        """
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'developer', 'dvt', 'pkill', _bbundleId, '--bundle'),
            _b超时秒=60)
        return _b文本 or '已发出停止指令'

    def f安装IPA(self, _budid, _bipa路径) -> str:
        """apps install <ipa>（大文件建议 300s+ 超时由调用方控制）。"""
        if not _bipa路径 or not os.path.isfile(_bipa路径):
            raise cIos错误(f'IPA 文件不存在：{_bipa路径}')
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'apps', 'install', _bipa路径), _b超时秒=600)
        return _b文本 or '安装完成'

    def f卸载应用(self, _budid, _bbundleId) -> str:
        """apps uninstall <bundleId>。"""
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'apps', 'uninstall', _bbundleId), _b超时秒=90)
        return _b文本 or '卸载完成'

    # ------------------------------------------------------------------
    # 截图 / 崩溃
    # ------------------------------------------------------------------
    def f截图(self, _budid, _b保存路径) -> str:
        """developer screenshot <路径>；失败回退 developer dvt screenshot <路径>。

        两条路径都会把 PNG 写到指定文件，成功即返回该路径。
        """
        _b输出目录 = os.path.dirname(_b保存路径)
        if _b输出目录 and not os.path.isdir(_b输出目录):
            raise cIos错误(f'保存目录不存在：{_b输出目录}')
        _b主路径 = self.f构造命令(_budid, 'developer', 'screenshot', _b保存路径)
        try:
            self.f运行命令(_b主路径, _b超时秒=90)
        except cIos错误 as _b首个异常:
            _b备用 = self.f构造命令(_budid, 'developer', 'dvt', 'screenshot', _b保存路径)
            try:
                self.f运行命令(_b备用, _b超时秒=90)
            except cIos错误:
                raise _b首个异常
        if os.path.isfile(_b保存路径):
            return _b保存路径
        raise cIos错误('截图命令已执行，但未找到输出图片文件：' + _b保存路径)

    def f崩溃列表(self, _budid='') -> list:
        """crash ls → 崩溃报告路径列表（该命令输出为逐行纯文本，非 JSON）。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'crash', 'ls'), _b超时秒=90)
        return [_b行.strip() for _b行 in _b文本.splitlines() if _b行.strip()]

    def f拷贝崩溃(self, _budid, _b匹配模式, _b目标目录) -> str:
        """crash pull <目标目录> --match <匹配模式>，把匹配的崩溃报告拉到本机。"""
        if not os.path.isdir(_b目标目录):
            raise cIos错误(f'目标目录不存在：{_b目标目录}')
        _b参数 = self.f构造命令(_budid, 'crash', 'pull', _b目标目录)
        if _b匹配模式:
            _b参数.extend(['--match', str(_b匹配模式)])
        _b文本 = self.f运行命令(_b参数, _b超时秒=180)
        return _b文本 or '拷贝完成'

    def f读取崩溃报告(self, _budid, _b崩溃文件, _b临时目录) -> str:
        """把单份崩溃报告拉到本机临时目录并返回其文本内容（供详情查看）。"""
        if not os.path.isdir(_b临时目录):
            os.makedirs(_b临时目录, exist_ok=True)
        import re
        _b文件名 = os.path.basename(str(_b崩溃文件))
        _b参数 = self.f构造命令(_budid, 'crash', 'pull', _b临时目录)
        _b参数.extend(['--match', re.escape(_b文件名) if _b文件名 else '.'])
        self.f运行命令(_b参数, _b超时秒=180)

        _b本地文件 = os.path.join(_b临时目录, _b文件名)
        if not os.path.isfile(_b本地文件):
            # 远端路径可能带目录层级，退化为按 basename 在本目录内模糊匹配
            _b候选 = [os.path.join(_b临时目录, _b名)
                      for _b名 in os.listdir(_b临时目录)
                      if _b文件名 in _b名]
            if not _b候选:
                _b候选 = [os.path.join(_b临时目录, _b名)
                          for _b名 in os.listdir(_b临时目录)
                          if os.path.isfile(os.path.join(_b临时目录, _b名))]
            # 优先取最近修改的一份
            _b本地文件 = max(_b候选, key=os.path.getmtime) if _b候选 else ''
        if not _b本地文件 or not os.path.isfile(_b本地文件):
            raise cIos错误(f'崩溃报告拉取后未找到本地文件：{_b崩溃文件}')
        try:
            with open(_b本地文件, 'r', encoding='utf-8', errors='replace') as _b文件流:
                return _b文件流.read()
        except OSError as _b异常:
            raise cIos错误(f'读取崩溃报告失败：{_b异常}')

    # ------------------------------------------------------------------
    # 状态采集
    # ------------------------------------------------------------------
    def f抓取日志(self, _budid='', _b时长秒=6.0, _b最大行=200) -> str:
        """syslog live 为流式命令：限制时长抓取一段后截断，返回最近 _b最大行。"""
        if not self.f可用():
            raise cIos错误(f安装指引())
        _b参数 = self.f构造命令(_budid, 'syslog', 'live')
        self.f日志('$ ' + ' '.join(_b参数) + f'  （截取前 {_b时长秒:.0f} 秒）')
        try:
            _b结果 = subprocess.run(
                _b参数,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=_b时长秒,
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0,
            )
            _b输出 = _b结果.stdout or _b结果.stderr or ''
        except subprocess.TimeoutExpired as _b异常:
            # 超时是预期的「截流」手段
            _b输出 = ''
            if _b异常.stdout:
                try:
                    _b输出 = _b异常.stdout.decode('utf-8', errors='replace')
                except Exception:
                    _b输出 = str(_b异常.stdout)
        except FileNotFoundError:
            raise cIos错误(f安装指引())
        _b行 = [_b行.strip() for _b行 in _b输出.splitlines() if _b行.strip()]
        return '\n'.join(_b行[-_b最大行:])

    def f采样系统监控(self, _budid='', _b时长秒=5.0) -> dict:
        """developer dvt sysmon system → 一帧系统监控数据。

        pymobiledevice3 的 sysmon system 是一次性命令（采满一帧即退出），
        输出为「键: 值」纯文本，此处解析成 dict；解析不到时把原文塞进 raw。
        """
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'developer', 'dvt', 'sysmon', 'system'),
            _b超时秒=max(20.0, _b时长秒 + 10.0))
        _b帧 = {}
        for _b行 in _b文本.splitlines():
            _b行 = _b行.strip()
            if not _b行 or ':' not in _b行:
                continue
            _b键, _, _b值 = _b行.partition(':')
            _b帧[_b键.strip()] = _b值.strip()
        if not _b帧 and _b文本:
            _b帧['raw'] = _b文本
        return _b帧

    def f读取电池(self, _budid='') -> dict:
        """diagnostics battery single → 电池信息 dict。"""
        _b数据 = self.f运行Json(
            self.f构造命令(_budid, 'diagnostics', 'battery', 'single'), _b超时秒=60)
        return _b数据 if isinstance(_b数据, dict) else {}

    def f读取磁盘(self, _budid='') -> dict:
        """磁盘容量。

        能力差异：pymobiledevice3 未提供磁盘容量查询子命令（go-ios diskspace 无对应实现），
        因此这里不伪造数据，而是返回说明性字典，让 UI 给出明确提示。
        """
        return {
            '说明': 'pymobiledevice3 未提供磁盘容量查询子命令（go-ios diskspace 无对应实现）',
            '替代方案': [
                '「设备信息」可查看设备存储相关字段',
                'pymobiledevice3 apps list --calculate-sizes 可查看各应用占用',
                'pymobiledevice3 afc shell 内执行 info 可看 AFC 文件系统信息',
            ],
        }

    def f读取进程(self, _budid='') -> list:
        """processes ps → 进程数组。

        pymobiledevice3 返回 {pid: {ProcessName: …}} 字典，此处摊平为
        [{pid, name}]，使上层沿用旧字段读取方式。
        """
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'processes', 'ps'), _b超时秒=60)
        if not isinstance(_b数据, dict):
            return []
        _b结果 = []
        for _bpid, _b信息 in _b数据.items():
            if isinstance(_b信息, dict):
                _b名称 = _b信息.get('ProcessName') or _b信息.get('name') or ''
            else:
                _b名称 = str(_b信息)
            _b结果.append({'pid': _bpid, 'name': _b名称})
        return _b结果

    # ------------------------------------------------------------------
    # 调试通道（隧道 / 开发者模式 / 镜像）
    # ------------------------------------------------------------------
    def f检查隧道(self) -> list:
        """查询本机 tunneld 常驻服务上的活动隧道（未运行返回空列表）。

        iOS 17+ 的隧道 pymobiledevice3 会按需自动建立（userspace，免 root），
        因此"没有常驻隧道"不等于"不能调试"，UI 侧按 warn 而非 bad 展示。
        """
        return f查询隧道服务()

    def f启动隧道(self) -> str:
        """启动 tunneld 常驻服务（-d 后台化），加速重复连接；非必需。"""
        _b参数 = list(self._b命令前缀) + ['remote', 'tunneld', '--daemonize']
        _b文本 = self.f运行命令(_b参数, _b超时秒=120)
        return _b文本 or f'tunneld 已启动（{_b隧道默认地址[0]}:{_b隧道默认地址[1]}）'

    def f读取开发者模式(self, _budid='') -> str:
        """amfi developer-mode-status → 开发者模式状态文本。"""
        try:
            _b数据 = self.f运行Json(
                self.f构造命令(_budid, 'amfi', 'developer-mode-status'), _b超时秒=60)
        except cIos错误:
            return '查询失败'
        if isinstance(_b数据, bool):
            return 'Developer Mode: enabled' if _b数据 else 'Developer Mode: disabled'
        return str(_b数据)

    def f开启开发者模式(self, _budid='') -> str:
        """amfi enable-developer-mode → 开启开发者模式（设备可能提示重启）。"""
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'amfi', 'enable-developer-mode'), _b超时秒=120)
        return _b文本 or '开发者模式已开启'

    def f挂载开发者镜像(self, _budid='') -> str:
        """mounter auto-mount → 自动下载并挂载开发者镜像（较慢，UI 侧放线程）。"""
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'mounter', 'auto-mount'), _b超时秒=300)
        return _b文本 or '镜像挂载完成'

    def f检查镜像(self, _budid='') -> list:
        """mounter list → 已挂载镜像列表。"""
        try:
            _b数据 = self.f运行Json(
                self.f构造命令(_budid, 'mounter', 'list'), _b超时秒=60)
        except cIos错误:
            return []
        return _b数据 if isinstance(_b数据, list) else []

    # ------------------------------------------------------------------
    # 代理 / 描述文件（抓包刚需，pymobiledevice3 独有能力）
    # ------------------------------------------------------------------
    def f安装HTTP代理(self, _budid='', _b服务器='', _b端口=8888) -> str:
        """profile install-http-proxy <server> <port> → 安装全局 HTTP 代理描述文件。

        用于抓包：把设备流量导向本机代理（如 mitmproxy / Charles / Fiddler 监听端口）。
        描述文件安装到设备后，会在设备上弹出确认框，需在设备点击「允许」才生效。
        """
        if not _b服务器:
            raise cIos错误('代理服务器地址不能为空（例如 192.168.1.10）')
        _b端口文本 = str(_b端口)
        if not _b端口文本.isdigit():
            raise cIos错误(f'代理端口必须是数字：{_b端口}')
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'profile', 'install-http-proxy',
                           str(_b服务器), _b端口文本),
            _b超时秒=90)
        return _b文本 or f'HTTP 代理描述文件已安装（{_b服务器}:{_b端口}），请在设备上确认'

    def f移除HTTP代理(self, _budid='') -> str:
        """profile remove-http-proxy → 移除此前安装的 HTTP 代理描述文件。"""
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'profile', 'remove-http-proxy'), _b超时秒=90)
        return _b文本 or 'HTTP 代理描述文件已移除'

    def f列出描述文件(self, _budid='') -> list:
        """profile list → 已安装描述文件列表（含代理 / 证书 / WiFi 等）。

        输出形态随 pymobiledevice3 版本可能是 JSON 数组 / JSON 对象 / 纯文本，
        这里做宽容归一：JSON 数组直接返回，对象包一层，文本塞进 raw 键。
        """
        _b数据 = self.f运行Json(
            self.f构造命令(_budid, 'profile', 'list'), _b超时秒=60)
        if isinstance(_b数据, list):
            return _b数据
        if isinstance(_b数据, dict):
            return [_b数据]
        if isinstance(_b数据, str) and _b数据.strip():
            return [{'raw': _b数据.strip()}]
        return []

    def f安装描述文件(self, _budid='', _b路径='') -> str:
        """profile install <路径> → 安装描述文件 / SSL 证书（抓包 HTTPS 解密刚需）。

        证书或 .mobileconfig 描述文件均可传入；安装后设备会弹出确认框。
        """
        if not _b路径 or not os.path.isfile(_b路径):
            raise cIos错误(f'描述文件/证书不存在：{_b路径}')
        _b文本 = self.f运行命令(
            self.f构造命令(_budid, 'profile', 'install', _b路径), _b超时秒=90)
        return _b文本 or '描述文件/证书已安装，请在设备上确认'

    # ------------------------------------------------------------------
    # 环境自检（供 环境自检对话框 / 主界面 使用）
    # ------------------------------------------------------------------
    def f执行环境自检(self) -> list:
        """逐项自检并返回 [{名称, 状态, 信息, 指引}]。

        状态取值：ok（绿）/ bad（红）/ warn（黄，可继续）/ none（灰，跳过）。
        """
        _b结果 = []
        # 1. 后端存在
        if self.f可用():
            _b前缀 = '【模拟模式】' if self.f是否模拟模式() else ''
            _b结果.append({
                '名称': 'pymobiledevice3 后端',
                '状态': 'ok',
                '信息': _b前缀 + f前缀说明(self._b命令前缀),
                '指引': '',
            })
        else:
            _b结果.append({
                '名称': 'pymobiledevice3 后端',
                '状态': 'bad',
                '信息': '未找到 pymobiledevice3',
                '指引': f安装指引(),
            })
            return _b结果  # 后续全部依赖后端，直接短路

        # 2. 版本
        try:
            _b版本 = self.f获取版本()
            _b结果.append({'名称': '版本', '状态': 'ok', '信息': _b版本, '指引': ''})
        except Exception as _b异常:
            _b结果.append({
                '名称': '版本', '状态': 'bad',
                '信息': str(_b异常), '指引': '运行 pymobiledevice3 version 排查',
            })

        # 3. 设备枚举
        try:
            _b设备 = self.f获取设备列表()
        except Exception as _b异常:
            _b结果.append({
                '名称': '设备枚举', '状态': 'bad',
                '信息': str(_b异常),
                '指引': 'pymobiledevice3 在 Windows 上需 usbmuxd 服务（127.0.0.1:27015）。'
                        '不必装完整 iTunes —— Microsoft Store 装「Apple Devices」/'
                        '「Apple Music」/「Apple TV」任一即可（自带 AMD 驱动），'
                        '装完插一次 iPhone 触发驱动加载。'
                        '验证：netstat -an | findstr 27015  应见 LISTENING。'
                        'Linux/macOS 需 usbmuxd 守护进程在跑。',
            })
            return _b结果
        if not _b设备:
            _b结果.append({
                '名称': '设备枚举', '状态': 'warn',
                '信息': '未发现设备（0 台）',
                '指引': '用数据线连接并解锁 iPhone/iPad → 弹出「信任此电脑」点击信任 → '
                        '刷新重试；若仍无设备，检查 Apple Mobile Device Service / usbmuxd',
            })
            _b结果.append({'名称': '开发者模式', '状态': 'none', '信息': '无设备，跳过', '指引': ''})
            _b结果.append({'名称': '开发者镜像', '状态': 'none', '信息': '无设备，跳过', '指引': ''})
            return _b结果
        _b结果.append({
            '名称': '设备枚举', '状态': 'ok',
            '信息': f'发现 {len(_b设备)} 台设备', '指引': '',
        })

        # 4. 隧道（iOS 17+ 由 pymobiledevice3 按需自动建立，无常驻隧道仅作提示）
        _b隧道 = self.f检查隧道()
        _b结果.append({
            '名称': '隧道状态',
            '状态': 'ok' if _b隧道 else 'warn',
            '信息': f'常驻隧道 {len(_b隧道)} 条' if _b隧道 else '无常驻隧道（pymobiledevice3 将按需自动建立）',
            '指引': 'iOS 17+ 的隧道 pymobiledevice3 默认按需自动建立（userspace，免 root）；'
                    '如需加速重复连接，可点「隧道」按钮启动 tunneld 常驻服务'
                    f'（{_b隧道默认地址[0]}:{_b隧道默认地址[1]}）',
        })

        # 5-7. 首台设备：开发者模式 / 镜像 / 基本信息
        _b在线 = [d for d in _b设备 if (d.get('udid') or d.get('UniqueDeviceID'))]
        if not _b在线:
            _b结果.append({'名称': '开发者模式', '状态': 'none', '信息': '无可用 UDID，跳过', '指引': ''})
            _b结果.append({'名称': '开发者镜像', '状态': 'none', '信息': '无可用 UDID，跳过', '指引': ''})
            return _b结果

        _b第一台 = _b在线[0]
        _budid = str(_b第一台.get('udid') or _b第一台.get('UniqueDeviceID') or '')
        _b设备名 = _b第一台.get('DeviceName') or _b第一台.get('name') or _budid[:16]
        _b结果.append({
            '名称': '设备', '状态': 'ok',
            '信息': f'{_b设备名}  UDID: {_budid}', '指引': '',
        })

        # 开发者模式
        try:
            _b模式 = self.f读取开发者模式(_budid)
            _b小写 = _b模式.lower()
            _b开启 = ('enabled' in _b小写 or 'true' in _b小写 or '开启' in _b模式)
            _b结果.append({
                '名称': '开发者模式', '状态': 'ok' if _b开启 else 'warn',
                '信息': _b模式.strip()[:120] or '查询结果为空',
                '指引': '未开启请在设备「设置 → 隐私与安全性 → 开发者模式」手动开启'
                        '（或点主界面「开发者模式」按钮），设备会重启一次',
            })
        except Exception as _b异常:
            _b结果.append({
                '名称': '开发者模式', '状态': 'warn',
                '信息': str(_b异常), '指引': '低系统版本可能不支持，可忽略',
            })

        # 镜像
        try:
            _b镜像 = self.f检查镜像(_budid)
            _b结果.append({
                '名称': '开发者镜像', '状态': 'ok' if _b镜像 else 'warn',
                '信息': f'已挂载 {len(_b镜像)} 个' if _b镜像 else '未挂载',
                '指引': '未挂载请点主界面「挂载镜像」按钮执行 mounter auto-mount'
                        '（首次需联网下载）',
            })
        except Exception as _b异常:
            _b结果.append({
                '名称': '开发者镜像', '状态': 'warn',
                '信息': str(_b异常), '指引': '可点「挂载镜像」手动重试',
            })
        return _b结果
