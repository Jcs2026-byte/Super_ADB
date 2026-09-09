# -*- coding: utf-8 -*-
"""
go-ios 桥接（Super_ADB_Win/工具/Ios调试模块/goIos桥接.py）
=========================================================
以 MIT 许可的 go-ios 静态二进制作为 iOS 后端，通过「子进程调用 + JSON 解析」
接入，与 Android 侧「Python UI + adb 外部二进制」形态一致。

对外主类：cIos设备操作
    - 二进制自动发现（资源目录 / PATH / 常见安装位置 / 环境变量 SUPER_ADB_IOS_BIN）
    - 统一超时执行、中文错误、JSON 容错
    - 覆盖 go-ios 常用子命令封装（供 UI/对话框调用）

环境自检：f执行环境自检() 逐项返回 {名称, 状态, 信息, 指引}，
供「iOS 环境自检面板」红绿灯展示（对应接入方案 §8）。

命名规范：类名前缀 c、方法名前缀 f、变量名前缀 b（新建代码全遵守）。
"""
import json
import os
import shutil
import subprocess
import sys
import threading

# 系统兼容：Windows 下 go-ios 二进制名 ios.exe；Unix 为 ios
_bWIN = sys.platform.startswith('win')
_b可执行后缀 = '.exe' if _bWIN else ''

# 二进制默认搜索顺序（含随包分发资源目录）
_b候选相对路径 = (
    os.path.join('资源', 'ios' + _b可执行后缀),   # 随包分发位（Super_ADB_Win/资源/ios.exe）
    os.path.join('..', '资源', 'ios' + _b可执行后缀),  # 入口在项目启动入口/ 时
)


class cIos错误(Exception):
    """iOS 桥接统一异常：消息面向用户、可读。"""


def f查找Ios二进制() -> str:
    """按优先级查找 ios 可执行文件，找不到返回空字符串。

    查找顺序：
        1. 环境变量 SUPER_ADB_IOS_BIN
        2. 项目资源目录（随包分发 ios.exe）
        3. PATH 中的 ios
        4. 常见安装目录（npm 全局 / go bin / Homebrew）
    """
    _b环境指定 = os.environ.get('SUPER_ADB_IOS_BIN', '').strip()
    if _b环境指定 and os.path.isfile(_b环境指定):
        return _b环境指定

    # 从当前文件位置向上回溯 项目根（Super_ADB_Win/），命中 资源/ios.exe
    _b当前目录 = os.path.dirname(os.path.abspath(__file__))
    _b项目根 = os.path.dirname(os.path.dirname(_b当前目录))  # 工具/Ios调试模块 → Super_ADB_Win
    for _b相对 in _b候选相对路径:
        _b候选 = os.path.normpath(os.path.join(_b项目根, _b相对))
        if os.path.isfile(_b候选):
            return _b候选

    # PATH 查找
    _bwhich = shutil.which('ios')
    if _bwhich:
        return _bwhich

    # 常见安装位置兜底（不阻塞，找不到就返回空让调用方提示）
    _b家目录 = os.path.expanduser('~')
    _b常见目录 = []
    if _bWIN:
        _b常见目录 = [
            os.path.join(_b家目录, 'AppData', 'Roaming', 'npm', 'ios.cmd'),
            os.path.join(_b家目录, 'go', 'bin', 'ios.exe'),
        ]
    else:
        _b常见目录 = [
            '/usr/local/bin/ios',
            '/opt/homebrew/bin/ios',
            os.path.join(_b家目录, 'go', 'bin', 'ios'),
            os.path.join(_b家目录, '.local', 'bin', 'ios'),
        ]
    for _b路径 in _b常见目录:
        if os.path.isfile(_b路径):
            return _b路径
    return ''


def f安装指引() -> str:
    """ios 二进制缺失时给用户的可执行修复指引。"""
    _b行 = [
        '未找到 go-ios 二进制（ios）。任选一种方式安装后重试：',
        '  1) npm 全局安装：npm i -g go-ios',
        '  2) 下载官方 release：https://github.com/danielpaulus/go-ios/releases'
        '（Windows 解压得到 ios.exe，放到本工具 资源/ 目录即可被自动发现）',
        '  3) macOS：brew install danielpaulus/tap/go-ios',
        '也可设置环境变量 SUPER_ADB_IOS_BIN 指向 ios 可执行文件的绝对路径。',
    ]
    return '\n'.join(_b行)


class cIos设备操作:
    """go-ios 子进程桥接（新建代码遵循 c/f/b 前缀 + 中文命名）。

    用法：
        _b工具 = cIos设备操作(b日志回调=主窗口.日志)
        _b设备 = _b工具.f获取设备列表()
    所有方法同步执行，耗时命令请放线程池（UI 侧与 Android 命令工作器一致）。
    """

    def __init__(self, b日志回调=None):
        self._b日志回调 = b日志回调
        self._b二进制路径 = f查找Ios二进制()
        self._b检测锁 = threading.Lock()  # 二进制路径刷新并发保护

    # ------------------------------------------------------------------
    # 基础能力
    # ------------------------------------------------------------------
    def f刷新二进制路径(self):
        """重新探测二进制路径（用户安装 ios 后调用）。"""
        with self._b检测锁:
            self._b二进制路径 = f查找Ios二进制()
        return self._b二进制路径

    def f可用(self) -> bool:
        """go-ios 二进制是否就绪。"""
        return bool(self._b二进制路径 and os.path.isfile(self._b二进制路径))

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
        """拼出 ios 完整命令行。_b子命令元素保持顺序；udid 为空则交给 go-ios 默认第一台设备。"""
        _b命令 = [self._b二进制路径]
        if _budid:
            _b命令.append('--udid=' + _budid)
        _b命令.extend(str(x) for x in _b子命令)
        return _b命令

    def f运行命令(self, _b参数, _b超时秒=30.0) -> str:
        """执行 ios 命令并返回标准输出文本；非零返回码/异常转 cIos错误（中文信息）。"""
        if not self.f可用():
            raise cIos错误(f安装指引())
        _b显示 = ' '.join(str(x) for x in _b参数)
        self.f日志('$ ' + _b显示)
        try:
            _b结果 = subprocess.run(
                _b参数,
                capture_output=True,
                text=True,
                timeout=_b超时秒,
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0,
            )
        except subprocess.TimeoutExpired:
            raise cIos错误(f'命令超时（>{_b超时秒:.0f}s）：{_b显示}')
        except FileNotFoundError:
            raise cIos错误(f安装指引())
        except OSError as _b异常:
            raise cIos错误(f'启动 ios 失败：{_b异常}')
        _b输出 = (_b结果.stdout or '').strip()
        if _b结果.returncode != 0:
            _b原因 = (_b结果.stderr or _b输出 or '未知错误').strip()
            # 截取首行有意义的报错
            _b首行 = _b原因.splitlines()[0] if _b原因.splitlines() else _b原因
            if len(_b首行) > 160:
                _b首行 = _b首行[:160] + '…'
            raise cIos错误(f'ios 命令失败（{_b结果.returncode}）：{_b首行}\n{_b显示}')
        return _b输出

    def f运行Json(self, _b参数, _b超时秒=30.0):
        """执行 ios 命令并把 stdout 当 JSON 解析；不是 JSON 时原样返回文本。"""
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
        """ios list → 设备数组。每项保留原始字段（udid / name 等），UI 自行容错。"""
        _b数据 = self.f运行Json(self.f构造命令('', 'list'), _b超时秒=20)
        if _b数据 is None:
            return []
        if isinstance(_b数据, list):
            return [_b设备 for _b设备 in _b数据 if isinstance(_b设备, dict)]
        if isinstance(_b数据, dict) and isinstance(_b数据.get('devices'), list):
            return _b数据['devices']
        return []

    def f获取版本(self) -> str:
        """ios version → 人类可读版本串。"""
        _b数据 = self.f运行Json(self.f构造命令('', 'version'), _b超时秒=20)
        if isinstance(_b数据, dict):
            # 常见字段：version / go-ios / commit …
            _b版本 = _b数据.get('version') or _b数据.get('Version') or ''
            _b其余 = ' '.join(f'{k}={v}' for k, v in _b数据.items()
                              if k not in ('version', 'Version') and not str(k).startswith('go'))
            _b返回 = ('版本 ' + str(_b版本)) if _b版本 else str(_b数据)
            if _b其余:
                _b返回 += ' ｜ ' + _b其余
            return _b返回
        return str(_b数据)

    def f获取设备信息(self, _budid='') -> dict:
        """ios info → 设备信息字典（原始字段保留，UI 层做中文映射）。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'info'), _b超时秒=40)
        if isinstance(_b数据, dict):
            return _b数据
        return {}

    def f获取设备名称(self, _budid='') -> str:
        """快速拿设备名（info 失败时不影响调用方）。"""
        try:
            _b数据 = self.f获取设备信息(_budid)
            return str(_b数据.get('DeviceName') or _b数据.get('deviceName') or '')
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # 应用操作
    # ------------------------------------------------------------------
    def f获取应用列表(self, _budid='', _b只要简表=True) -> list:
        """ios apps → 应用数组。_b只要简表=True 追加 --list（bundle id/名称/版本）。"""
        _b命令 = self.f构造命令(_budid, 'apps')
        if _b只要简表:
            _b命令.append('--list')
        _b数据 = self.f运行Json(_b命令, _b超时秒=60)
        if isinstance(_b数据, list):
            return _b数据
        if isinstance(_b数据, dict):
            # 部分版本返回 {apps: [...]}
            for _b键 in ('apps', 'result', 'data'):
                if isinstance(_b数据.get(_b键), list):
                    return _b数据[_b键]
        return []

    def f启动应用(self, _budid, _bbundleId) -> str:
        """ios launch <bundleId>。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'launch', _bbundleId), _b超时秒=40)
        return _b文本 or '已发出启动指令'

    def f停止应用(self, _budid, _bbundleId) -> str:
        """ios kill <bundleId>（go-ios 支持按 bundle id / pid / 进程名结束）。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'kill', _bbundleId), _b超时秒=40)
        return _b文本 or '已发出停止指令'

    def f安装IPA(self, _budid, _bipa路径) -> str:
        """ios install --path=<ipa> 安装应用（大文件建议 300s+ 超时由调用方控制）。"""
        if not _bipa路径 or not os.path.isfile(_bipa路径):
            raise cIos错误(f'IPA 文件不存在：{_bipa路径}')
        _b参数 = self.f构造命令(_budid, 'install', '--path=' + _bipa路径)
        _b文本 = self.f运行命令(_b参数, _b超时秒=600)
        return _b文本 or '安装完成'

    def f卸载应用(self, _budid, _bbundleId) -> str:
        """ios uninstall <bundleId>。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'uninstall', _bbundleId), _b超时秒=60)
        return _b文本 or '卸载完成'

    # ------------------------------------------------------------------
    # 截图 / 崩溃
    # ------------------------------------------------------------------
    def f截图(self, _budid, _b保存路径) -> str:
        """ios screenshot --output=<路径>。成功返回实际保存路径。"""
        _b输出目录 = os.path.dirname(_b保存路径)
        if _b输出目录 and not os.path.isdir(_b输出目录):
            raise cIos错误(f'保存目录不存在：{_b输出目录}')
        _b参数 = self.f构造命令(_budid, 'screenshot', '--output=' + _b保存路径)
        _b文本 = self.f运行命令(_b参数, _b超时秒=60)
        # 部分版本 stdout 返回 {"filename": "..."}，优先取它
        if _b文本:
            try:
                _b数据 = json.loads(_b文本)
                if isinstance(_b数据, dict):
                    _b名字 = _b数据.get('filename') or _b数据.get('path') or _b数据.get('file')
                    if _b名字 and os.path.isfile(str(_b名字)):
                        return str(_b名字)
            except json.JSONDecodeError:
                pass
        if os.path.isfile(_b保存路径):
            return _b保存路径
        # 兜底：go-ios 也可能写到当前目录（默认文件名带 udid/时间戳），尝试找回
        _b当前目录 = os.getcwd()
        try:
            _b最新 = max(
                (os.path.join(_b当前目录, _b文件)
                 for _b文件 in os.listdir(_b当前目录)
                 if _b文件.lower().endswith(('.png', '.jpg', '.jpeg', '.heic'))
                 and _b文件.startswith(('screenshot', 'ScreenShot', 'ios'))),
                key=os.path.getmtime, default=None)
            if _b最新:
                return _b最新
        except OSError:
            pass
        raise cIos错误('截图命令已执行，但未找到输出图片文件。\n' + (_b文本 or ''))

    def f崩溃列表(self, _budid='') -> list:
        """ios crash ls → 崩溃报告文件名列表。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'crash', 'ls'), _b超时秒=60)
        if isinstance(_b数据, list):
            return [str(x) for x in _b数据]
        if isinstance(_b数据, dict):
            for _b键 in ('crashes', 'files', 'result'):
                if isinstance(_b数据.get(_b键), list):
                    return [str(x) for x in _b数据[_b键]]
        return []

    def f拷贝崩溃(self, _budid, _b匹配模式, _b目标目录) -> str:
        """ios crash cp <pattern> <targetDir>，把匹配的崩溃报告拷到本机。"""
        if not os.path.isdir(_b目标目录):
            raise cIos错误(f'目标目录不存在：{_b目标目录}')
        _b参数 = self.f构造命令(_budid, 'crash', 'cp', _b匹配模式, _b目标目录)
        _b文本 = self.f运行命令(_b参数, _b超时秒=120)
        return _b文本 or '拷贝完成'

    def f读取崩溃报告(self, _budid, _b崩溃文件, _b临时目录) -> str:
        """把单份崩溃报告拷到本机临时目录并返回其文本内容（供详情查看）。"""
        if not os.path.isdir(_b临时目录):
            os.makedirs(_b临时目录, exist_ok=True)
        # go-ios crash cp 的参数形式：cp <pattern> <dir>
        self.f运行命令(
            self.f构造命令(_budid, 'crash', 'cp', _b崩溃文件, _b临时目录),
            _b超时秒=120,
        )
        # 拷贝后按文件名在本机找回（可能存在 转义/重命名，逐个匹配兜底）
        _b本地文件 = os.path.join(_b临时目录, os.path.basename(_b崩溃文件))
        if not os.path.isfile(_b本地文件):
            _b候选 = [os.path.join(_b临时目录, _b名)
                     for _b名 in os.listdir(_b临时目录)
                     if os.path.isfile(os.path.join(_b临时目录, _b名))]
            _b本地文件 = _b候选[0] if len(_b候选) == 1 else (_b候选[0] if _b候选 else '')
        if not _b本地文件 or not os.path.isfile(_b本地文件):
            raise cIos错误(f'崩溃报告拷贝后未找到本地文件：{_b崩溃文件}')
        try:
            with open(_b本地文件, 'r', encoding='utf-8', errors='replace') as _b文件流:
                return _b文件流.read()
        except OSError as _b异常:
            raise cIos错误(f'读取崩溃报告失败：{_b异常}')

    # ------------------------------------------------------------------
    # 状态采集（推式命令 → 超时截流取最近帧/段）
    # ------------------------------------------------------------------
    def f抓取日志(self, _budid='', _b时长秒=6.0, _b最大行=200) -> str:
        """ios syslog 为流式命令：限制时长抓取一段后截断，返回最近 _b最大行。"""
        if not self.f可用():
            raise cIos错误(f安装指引())
        _b参数 = self.f构造命令(_budid, 'syslog')
        self.f日志('$ ' + ' '.join(_b参数) + f'  （截取前 {_b时长秒:.0f} 秒）')
        try:
            _b结果 = subprocess.run(
                _b参数,
                capture_output=True,
                text=True,
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
        """ios sysmontap 为流式命令：订阅 _b时长秒，返回最近一帧 JSON。

        返回 dict（字段以实际 JSON 为准，适配层用别名容错）：
            常见键：cpu_pct / per_core / mem_used_mb / ts / raw 等
        解析失败时把最后一帧原文塞进 raw 返回。
        """
        if not self.f可用():
            raise cIos错误(f安装指引())
        _b参数 = self.f构造命令(_budid, 'sysmontap')
        _b帧 = {}
        try:
            _b进程 = subprocess.Popen(
                _b参数,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0,
            )
            import time
            _b截止 = time.time() + _b时长秒
            while time.time() < _b截止:
                _b行 = _b进程.stdout.readline()
                if not _b行:
                    break
                _b行 = _b行.strip()
                if not _b行:
                    continue
                try:
                    _b数据 = json.loads(_b行)
                    if isinstance(_b数据, dict):
                        _b帧 = _b数据
                except json.JSONDecodeError:
                    _b帧['raw'] = _b行
            _b进程.kill()
        except FileNotFoundError:
            raise cIos错误(f安装指引())
        except Exception as _b异常:
            _b帧['raw'] = f'采样异常：{_b异常}'
        return _b帧

    def f读取电池(self, _budid='') -> dict:
        """ios batterycheck → 电池信息 dict。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'batterycheck'), _b超时秒=40)
        return _b数据 if isinstance(_b数据, dict) else {}

    def f读取磁盘(self, _budid='') -> dict:
        """ios diskspace → 磁盘容量 dict。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'diskspace'), _b超时秒=40)
        return _b数据 if isinstance(_b数据, dict) else {}

    def f读取进程(self, _budid='') -> list:
        """ios ps → 进程数组。"""
        _b数据 = self.f运行Json(self.f构造命令(_budid, 'ps'), _b超时秒=40)
        if isinstance(_b数据, list):
            return [_b进程 for _b进程 in _b数据 if isinstance(_b进程, dict)]
        if isinstance(_b数据, dict) and isinstance(_b数据.get('processes'), list):
            return _b数据['processes']
        return []

    # ------------------------------------------------------------------
    # 调试通道（隧道 / 开发者模式 / 镜像）
    # ------------------------------------------------------------------
    def f检查隧道(self) -> list:
        """ios tunnel ls → 已运行隧道列表。"""
        try:
            _b数据 = self.f运行Json(self.f构造命令('', 'tunnel', 'ls'), _b超时秒=20)
        except cIos错误:
            return []
        if isinstance(_b数据, list):
            return _b数据
        return []

    def f启动隧道(self) -> str:
        """ios tunnel start → 建立 iOS 17+ 隧道（Windows 需管理员权限）。"""
        _b文本 = self.f运行命令(self.f构造命令('', 'tunnel', 'start'), _b超时秒=60)
        return _b文本 or '隧道已启动'

    def f读取开发者模式(self, _budid='') -> str:
        """ios devmode get → 开发者模式状态文本。"""
        try:
            return self.f运行命令(self.f构造命令(_budid, 'devmode', 'get'), _b超时秒=40)
        except cIos错误:
            return '查询失败'

    def f开启开发者模式(self, _budid='') -> str:
        """ios devmode enable → 开启开发者模式（设备可能提示重启）。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'devmode', 'enable'), _b超时秒=60)
        return _b文本 or '开发者模式已开启'

    def f挂载开发者镜像(self, _budid='') -> str:
        """ios image auto → 自动下载并挂载开发者镜像（较慢，UI 侧放线程）。"""
        _b文本 = self.f运行命令(self.f构造命令(_budid, 'image', 'auto'), _b超时秒=300)
        return _b文本 or '镜像挂载完成'

    def f检查镜像(self, _budid='') -> list:
        """ios image list → 已挂载镜像列表。"""
        try:
            _b数据 = self.f运行Json(self.f构造命令(_budid, 'image', 'list'), _b超时秒=40)
        except cIos错误:
            return []
        if isinstance(_b数据, list):
            return _b数据
        return []

    # ------------------------------------------------------------------
    # 环境自检（供 环境自检对话框 / 主界面 使用）
    # ------------------------------------------------------------------
    def f执行环境自检(self) -> list:
        """逐项自检并返回 [{名称, 状态, 信息, 指引}]。

        状态取值：ok（绿）/ bad（红）/ warn（黄，可继续）/ none（灰，跳过）。
        """
        _b结果 = []
        # 1. 二进制存在
        if self.f可用():
            _b结果.append({
                '名称': 'go-ios 二进制',
                '状态': 'ok',
                '信息': self._b二进制路径,
                '指引': '',
            })
        else:
            _b结果.append({
                '名称': 'go-ios 二进制',
                '状态': 'bad',
                '信息': '未找到 ios 可执行文件',
                '指引': f安装指引(),
            })
            return _b结果  # 后续全部依赖二进制，直接短路

        # 2. 版本
        try:
            _b版本 = self.f获取版本()
            _b结果.append({
                '名称': '版本', '状态': 'ok',
                '信息': _b版本, '指引': '',
            })
        except Exception as _b异常:
            _b结果.append({
                '名称': '版本', '状态': 'bad',
                '信息': str(_b异常), '指引': '运行 ios version 排查',
            })

        # 3. 设备枚举
        try:
            _b设备 = self.f获取设备列表()
            if _b设备:
                _b结果.append({
                    '名称': '设备枚举', '状态': 'ok',
                    '信息': f'发现 {len(_b设备)} 台设备',
                    '指引': '',
                })
            else:
                _b结果.append({
                    '名称': '设备枚举', '状态': 'warn',
                    '信息': '未发现设备（0 台）',
                    '指引': '用数据线连接并解锁 iPhone/iPad → 弹出「信任此电脑」点击信任 → '
                            '刷新重试；若仍无设备，检查 iTunes/Apple 驱动是否安装',
                })
        except Exception as _b异常:
            _b结果.append({
                '名称': '设备枚举', '状态': 'bad',
                '信息': str(_b异常), '指引': '尝试以管理员身份运行本工具',
            })
            return _b结果

        # 4. 隧道（iOS 17+ 必需；报错多为权限/缺 wintun，按 warn 处理不阻断）
        try:
            _b隧道 = self.f检查隧道()
            _b结果.append({
                '名称': '隧道状态', '状态': 'ok',
                '信息': f'隧道 {len(_b隧道)} 条' if _b隧道 else '无活动隧道',
                '指引': 'iOS 17+ 需先「隧道」按钮或手动执行 ios tunnel start（Windows 管理员）；'
                        'iOS 16 及以下可跳过此步',
            })
        except Exception as _b异常:
            _b结果.append({
                '名称': '隧道状态', '状态': 'warn',
                '信息': f'查询失败：{_b异常}',
                '指引': 'Windows 需管理员权限 + wintun.dll（放入 C:/Windows/system32）',
            })

        # 5-7. 每个在线设备：开发者模式 / 镜像 / 基本信息（有设备才查）
        _b在线 = [d for d in _b设备 if (d.get('udid') or d.get('UDID'))]
        if not _b在线:
            _b结果.append({
                '名称': '开发者模式', '状态': 'none',
                '信息': '无设备，跳过', '指引': '',
            })
            _b结果.append({
                '名称': '开发者镜像', '状态': 'none',
                '信息': '无设备，跳过', '指引': '',
            })
            return _b结果

        _b第一台 = _b在线[0]
        _budid = str(_b第一台.get('udid') or _b第一台.get('UDID') or '')
        _b设备名 = _b第一台.get('name') or _b第一台.get('DeviceName') or _budid[:16]
        _b结果.append({
            '名称': '设备', '状态': 'ok',
            '信息': f'{_b设备名}  UDID: {_budid}',
            '指引': '',
        })

        # 开发者模式
        try:
            _b模式 = self.f读取开发者模式(_budid)
            _b小写 = _b模式.lower()
            _b开启 = ('enabled' in _b小写 or 'true' in _b小写 or '开启' in _b模式
                      or 'on' in _b小写 and 'unknown' not in _b小写)
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
                '指引': '未挂载请点主界面「挂载镜像」按钮执行 ios image auto'
                        '（首次需联网下载）',
            })
        except Exception as _b异常:
            _b结果.append({
                '名称': '开发者镜像', '状态': 'warn',
                '信息': str(_b异常), '指引': '可点「挂载镜像」手动重试',
            })
        return _b结果
