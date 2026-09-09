# Super_ADB 接入 iOS 技术方案（pymobiledevice3 主后端版）

版本：**v2.0** ｜ 日期：2026-09-09 ｜ 适用仓库：gitee Jcs2026/super_adb + github Jcs2026-byte/Super_ADB
项目现状：MIT 许可、PySide6 桌面端、已有完整 Android 性能监控与 HTML 报告导出能力。

> **v2.0 定位变更**：v1.0 是《iOS接入技术方案.md》（go-ios 主路径）的**平行备选方案**；
> 2026-09-09 决策 **iOS 后端整套切换为 pymobiledevice3**，本文成为 iOS 接入的**主方案文档**。
> go-ios 桥接降级为可选回退（配置项可切），新功能一律以 pymd3 为准。

---

## 变更记录（v1.0 → v2.0）

| # | 类型 | 修订内容 |
|---|---|---|
| 1 | 方向 | 主后端由"二选一备选"改为 **pymd3 唯一主后端**（go-ios 桥接保留为回退） |
| 2 | 纠错 | `--udid` 是**子命令级**选项，不能放在 `pymobiledevice3` 顶层（v1.0 骨架全部命令会报 no such option） |
| 3 | 纠错 | `developer dvt kill` 参数是 **PID 不是 bundle id**；按 bundle 停止用 `dvt pkill <bid> --bundle` |
| 4 | 纠错 | `remote tunneld` 是**常驻守护进程**，不能当"查询隧道列表"用（v1.0 的 `f检查隧道` 必然 5s 超时失败） |
| 5 | 纠错 | 骨架 3 处硬编码 `['pymobiledevice3', ...]`，绕过了 `SUPER_ADB_PYMD3_BIN` 与 PATH 查找结果 |
| 6 | 纠错 | lzfse **有 wheel**（cp38~cp312 win_amd64），并非"完全无 wheel"；仅 Python 3.13+ 才需现场编译 |
| 7 | 纠错 | 命令名：`mounter auto-mount`（非 auto）、`crash pull`（非 ls）、`core-profile-session`（非 kdump）、整机监控用 `sysmon system` |
| 8 | 补齐 | `IIosBackend` 抽象从 11 个方法补齐到 **25 业务 + 3 通用**（与现有 `goIos桥接.py` 1:1，否则回退时 AttributeError） |
| 9 | 新增 | §8「无真机联调（模拟器）」——换后端后模拟器必须按 pymd3 CLI 协议重写 |
| 10 | 对齐 | 目录结构/对话框文件名按仓库实际（`iOS环境自检对话框.py` 等带 iOS 前缀）；采样契约对齐现状（容错 dict 而非 dataclass） |

---

## 0. 决策摘要（先看这段）

| 项 | 决策 |
|---|---|
| 主后端 | **pymobiledevice3 11.10.3**（纯 Python，能力最全，iOS 17+ 隧道成熟） |
| 调用方式 | **CLI 子进程**（`pymobiledevice3 ...`），**不 in-process import** |
| go-ios 定位 | 保留 `goIos桥接.py` 作为**回退后端**，配置项 `ios_backend` 可切，但**不再新增 go-ios 能力** |
| GPL 处理 | pymd3 随包**不打**进主 exe；用户自行 `pip install`，主程序仅 spawn 其 CLI |
| 打包体积 | 主包增量 ≈ 0（不带 pymd3 及其依赖） |
| 许可证风险 | 中（GPL 进程边界灰区，见 §2），若闭源商用需法务确认；若开源可忽略 |
| Windows 硬门槛 | **lzfse 需现场编译**（Python 3.13+），须装 VS C++ Build Tools；或目标环境用 Python ≤3.12 直接吃现成 wheel |

---

## 1. 为什么选 pymobiledevice3（而不是 go-ios）

### 1.1 能力维度

| 能力 | go-ios | pymobiledevice3 | 说明 |
|---|---|---|---|
| 设备枚举/应用管理 | ✅ | ✅ | 打平 |
| 截图 | ✅ | ✅ `developer dvt screenshot`（实测 ~0.7s/张） | 打平 |
| syslog | ✅ 基础 | ✅ `syslog live`（含 debug，可 `-m` 过滤） | pymd3 更细 |
| **oslog 完整嗅探**（含 signpost） | ❌ | ✅ `developer dvt oslog` | pymd3 独有 |
| 崩溃拉取 | ✅ `crash ls/cp` | ✅ `crash pull <dir>` 批量 | pymd3 更省事 |
| 性能采样 | ✅ `sysmontap` | ✅ `dvt sysmon system`（整机 CPU/内存/磁盘/网络）+ `sysmon process`（进程级） | pymd3 覆盖面更广 |
| 进程 CPU/能耗 | ❌ | ✅ `dvt energy <pid>` / `sysmon process` | pymd3 独有 |
| **KDebug 跟踪**（类 strace） | ❌ | ✅ `dvt core-profile-session parse-live` | pymd3 独有 |
| **代理/描述文件/证书** | ❌ | ✅ `profile install-http-proxy` / `profile install <证书>` | pymd3 独有（抓包刚需） |
| **AFC 沙盒文件** | ❌ | ✅ `apps afc` / `afc shell` | pymd3 独有 |
| **Backup/Restore** | ❌ | ✅ `backup2 backup/restore` | pymd3 独有 |
| **WebInspector CDP** | ❌ | ✅ `webinspector ...` | pymd3 独有 |
| **PCAP 抓包** | ❌ | ✅ `pcap` | pymd3 独有 |
| iOS 17+ 隧道 | ✅ `tunnel start`（Win 需 wintun+管理员） | ✅ `lockdown start-tunnel`（17.4+）/ `remote tunneld` 守护进程 / macOS `--native` 免 root | pymd3 更成熟 |
| 跟进新 iOS | 中 | **快**（11.x 2026 仍高频发版） | 社区活跃 |

### 1.2 选 pymd3 的核心理由

1. **性能数据粒度**：Android 监控页要做 per-process CPU/内存，`dvt sysmon` 直接给结构化帧；go-ios 的 sysmontap 字段较粗。
2. **iOS 17+ 隧道**：`tunneld` 守护进程可自动建隧道；macOS 上 `--native` 隧道 piggyback remoted，**无需 sudo**；go-ios 在 Windows 必须 wintun.dll + 管理员。
3. **长期维护**：pymd3 是 iOS 自动化社区事实标准（tidevice3、LocationSimulator 均基于它）。
4. **纯 Python**：与主工程同语言；CLI 子进程调用与现有 `subprocess + json` 模式一致。
5. **扩展空间**：代理设置、证书安装、沙盒文件、备份、Web 自动化——这些 go-ios 完全没有，未来加功能不再换后端。

---

## 2. 许可证与打包体积（硬约束）

### 2.1 GPL-3.0 风险定性

- pymobiledevice3 是 **GPL-3.0-or-later**。
- **红线**：在 PyInstaller 打包的同一个 exe 里 `import pymobiledevice3`（in-process）→ 整个 exe 被认定为 GPL 衍生作品，必须全部开源。
- **灰区**：通过 `subprocess` 调用 pymd3 CLI（两个独立进程），FSF 倾向认为"仅把 GPL 程序当工具调用不构成衍生"，但存在争议。
- **本项目决策**：
  - 主仓库仍按 MIT 发布源码（源码层面不 import pymd3）；
  - 打包分发的 exe **不内置** pymd3，不写进 `hiddenimports` / `collect_submodules`；
  - 用户自行 `pip install pymobiledevice3`（文档指引 + 环境自检面板检测）；
  - 闭源商用前需法务复核；继续开源（当前状态）风险可控。

### 2.2 打包体积控制

| 方案 | 主包体积增量 | 结论 |
|---|---|---|
| ~~in-process import pymd3~~ | +40~80 MB（cryptography/libusb/psutil 等全进 exe） | **禁止**（体积 + GPL 传染） |
| **CLI 子进程（本方案）** | **≈ 0** | pymd3 是用户环境里的独立命令 |
| go-ios 回退 | +10~20 MB/平台（ios.exe 单二进制） | 可选 |

`.spec` 必须加的 excludes：

```python
excludes=[
    'pymobiledevice3', 'pymobiledevice3.*',
    'av', 'av.*',                      # PyAV/FFmpeg ~66MB，仅媒体功能用
    'IPython', 'IPython.*', 'jedi', 'parso', 'xonsh',
    'pygments', 'matplotlib_inline', 'stack_data',
    'fastapi', 'uvicorn', 'starlette', 'anyio', 'h11',
    'asgiref', 'ASGIMiddlewareStaticFile', 'ASGIWebDAV', 'aiofiles',
    'wsproto', 'hyperframe', 'qh3',
    'pyimg4', 'lzfse', 'pylzss', 'backports.zstd',
    'hexdump', 'pygnuutils', 'gpxpy',
]
```

> `cryptography` 若主工程 WiFi 配对已在用则保留；当前无线配对用 Python `ssl`，可排。

### 2.3 用户侧安装路径

环境自检面板检测到 pymd3 CLI 不可用时给出指引：

```bat
:: Windows 前提
::   1. iTunes（Microsoft Store 版）提供 usbmux 驱动
::   2. Python 3.13+ 需 Visual Studio C++ Build Tools（编译 lzfse）
::      https://visualstudio.microsoft.com/visual-cpp-build-tools/  → 勾选「使用 C++ 的桌面开发」
:: Linux:  sudo apt install usbmuxd libusb-1.0-0-dev
:: macOS:  brew install libusb openssl

pip install pymobiledevice3==11.10.3
```

不内置、不静默下载。用户装完点「重新检测」启用。

### 2.4 依赖实测结果（2026-09-09，Windows）

实测环境：系统 Python **3.14.7**（`D:\Python\Python314`）、另有 managed Python **3.13.12**。
`pip install --dry-run pymobiledevice3==11.10.3` 解析到 **约 90 个包**。

**坑 1 — lzfse 在 Python 3.13+ 无 wheel（事实修正）**

- 引入链（实测）：`lzfse>=0.4.2 (from pyimg4>=0.8.8 -> pymobiledevice3==11.10.3)`；pyimg4 服务镜像挂载/固件恢复路径。
- **修正 v1.0 的错误结论**：lzfse 0.4.2 在 PyPI **有** Windows 预编译 wheel，但只覆盖 **cp38~cp312**（win32/win_amd64）。
  - Python **≤ 3.12**：直接 `pip install` 即可，零编译。
  - Python **3.13 / 3.14**：无匹配 wheel → 回退 sdist → 现场编译 → 无 MSVC 时报
    `error: Microsoft Visual C++ 14.0 or greater is required.`
- **决策**：用户环境若为 3.13+，装 **VS C++ Build Tools**（约 3–6 GB，一次性）后现场编译通过。
- **检测**：环境自检面板用 **vswhere** 查询 MSVC（支持自定义安装路径，如 `D:\vs_buildtools`），找不到再兜底查常见路径并给下载链接。
- **捷径（可选）**：若用户不用镜像挂载/固件恢复，可用 `--no-deps` 最小集（§2.5）跳过 pyimg4，lzfse 与编译器都不需要。

**坑 2 — hexdump 只有 sdist（影响小）**

纯 Python 单文件 ~13 KB，无 C 扩展，装得上；可 vendor 进 `工具/Ios调试模块/_vendor/` 或忽略。

**坑 3 — 版本迭代快，必须锁版本**

11.x 引入了 `fastapi`/`uvicorn`/`starlette`/`ASGIWebDAV` 等（pymd3 自带 Web 调试服务）。
固定 `pymobiledevice3==11.10.3`，安装指引写死；环境自检显示实际版本并比对支持区间。

**省钱点**

| 包 | 体积 | 用途 | 处理 |
|---|---|---|---|
| av (PyAV) | ~66 MB | 媒体/HLS | 主 exe excludes；用户侧仍会装，不影响分发体积 |
| IPython+xonsh+jedi+pygments | ~24 MB | 交互 shell | 主 exe excludes |
| fastapi/uvicorn/starlette/ASGIWebDAV | ~15 MB | Web 服务 | 主 exe excludes |

### 2.5 最小依赖集（可选，跳过 pyimg4/lzfse）

```bat
pip install pymobiledevice3==11.10.3 --no-deps
pip install bpylist2 construct construct-typing asn1 pycryptodome ^
  psutil arrow chardet plumbum tqdm defusedxml coloredlogs ^
  typer typer-injector rich click colorama shellingham questionary prompt_toolkit ^
  xmltodict dataclass-wizard pydantic pydantic_core typing_extensions packaging ^
  pywin32 python-pcapng pycrashreport pykdebugparser ^
  wsproto qh3 hyperframe pytun-pmd3 ^
  cryptography requests opack2 developer_disk_image ifaddr srptools
```

> 相对 v1.0 补漏：`typer-injector`（11.x CLI 必需）、`developer_disk_image`（挂载镜像）、
> `cryptography`+`requests`（TLS/下载）、`opack2`、`shellingham`（typer 依赖）。
> **装完必须冒烟**（缺包时 CLI 会 ImportError）：
> ```bat
> pymobiledevice3 --help
> pymobiledevice3 usbmux list
> pymobiledevice3 apps list --help
> pymobiledevice3 developer dvt --help
> ```

---

## 3. 架构设计

### 3.1 分层

```
┌──────────────────────────────────────────────┐
│  UI 层（Ios调试模块 页 + 5 个对话框）         │
│   主入口_Ios调试.py（cIos调试Mixin）          │
└──────────────────┬───────────────────────────┘
                   │ 依赖抽象接口 IIosBackend
┌──────────────────▼───────────────────────────┐
│  桥接层（工具/Ios调试模块/）                 │
│   IIosBackend（ABC，25 业务 + 3 通用方法）    │
│   ├─ cPymd3设备操作   ← pymd3桥接.py（主）    │
│   └─ cIos设备操作     ← goIos桥接.py（回退）  │
│   后端工厂.py：按配置 ios_backend 实例化      │
└──────────────────┬───────────────────────────┘
                   │
        ┌──────────┴───────────┐
        ▼                      ▼
  pymobiledevice3 CLI     ios 二进制（可选回退）
  （GPL，用户自装）        （MIT，可选）
        │                      │
        └──────────┬───────────┘
                   ▼
        USB / usbmuxd / iOS17+ 隧道
                   ▼
              iPhone / iPad
```

### 3.2 后端选择配置

`配置/Super_ADB配置.json`：

```json
{
  "ios_backend": "pymd3",
  "_ios_backend_choices": ["pymd3", "goios", "auto"]
}
```

- `pymd3`（默认）：主后端；检测不到 CLI 就报错并给安装指引。
- `goios`：强制回退 go-ios。
- `auto`：优先 pymd3，不可用回退 go-ios（**要求两后端方法签名完全一致**，见 §5.1）。

### 3.3 采样契约（对齐现状）

现有 `goIos桥接.f采样系统监控()` 返回的是**容错 dict**（字段缺失置 None，UI 直接遍历打印），
不是严格 dataclass。pymd3 后端沿用同形态，**UI 零改动**：

```python
{
    'ts': 'HH:MM:SS',
    'cpu_pct': float | None,
    'per_core': {核号: 占用},
    'mem_used_mb': float | None, 'mem_total_mb': float | None,
    'batt_temp': float | None,
    'raw': 原始帧 JSON 截断（排障用）,
}
```

pymd3 侧由 `dvt sysmon system` 帧映射，字段名**待真机实测后固化**（§5.3 备注）。

---

## 4. 目录结构（按仓库实际文件名）

```
Super_ADB_Win/
├── 工具/Ios调试模块/
│   ├── goIos桥接.py              # 已有（go-ios 回退后端）
│   ├── goIos模拟器.py            # 已有（go-ios CLI 协议 stub）
│   ├── pymd3桥接.py              # 新增（pymobiledevice3 主后端）★
│   ├── pymd3命令映射.py          # 新增：CLI 子命令 ↔ 业务方法 对照表
│   ├── pymd3模拟器.py            # 新增：pymd3 CLI 协议 stub（无真机联调）★
│   └── 后端工厂.py               # 新增：按配置实例化 pymd3 / go-ios
├── 对话框/Ios调试模块/
│   ├── iOS环境自检对话框.py       # 扩展：加 pymd3 CLI / MSVC+lzfse / iTunes 驱动检测
│   ├── iOS设备信息对话框.py
│   ├── iOS日志对话框.py           # 改：命令由桥接 f构造命令 提供（不再写死 syslog）
│   ├── iOS截图预览.py
│   ├── iOS崩溃报告对话框.py
│   └── 公共任务.py
└── 项目启动入口/
    └── 主入口_Ios调试.py          # 改：调用后端工厂，不再直接 new cIos设备操作
```

三平台（Win/Mac/Linux）同步同构（md5 一致性校验）。

---

## 5. 核心代码骨架

### 5.1 后端抽象（`后端工厂.py`）—— 方法必须与现有 UI 1:1

现有 `goIos桥接.cIos设备操作` 对外共 **25 个业务方法 + 3 个通用方法**，UI/Mixin/对话框全部依赖；
**pymd3 后端必须全覆盖**，否则 `auto` 回退时触发 AttributeError。

```python
class IIosBackend(ABC):
    """iOS 后端抽象。所有方法同步，耗时调用由 UI 层放线程池。"""

    name: str = 'base'
    display_name: str = ''

    # ---- 通用（3）----
    @abstractmethod
    def f可用(self) -> bool: ...
    @abstractmethod
    def f刷新二进制路径(self) -> str: ...
    @abstractmethod
    def f构造命令(self, udid: str, *子命令) -> list: ...   # iOS日志对话框 直接调用

    # ---- 设备/信息（4）----
    @abstractmethod
    def f获取设备列表(self) -> list: ...
    @abstractmethod
    def f获取版本(self) -> str: ...
    @abstractmethod
    def f获取设备信息(self, udid: str = '') -> dict: ...
    @abstractmethod
    def f获取设备名称(self, udid: str = '') -> str: ...

    # ---- 应用（5）----
    @abstractmethod
    def f获取应用列表(self, udid: str = '', simple: bool = True) -> list: ...
    @abstractmethod
    def f启动应用(self, udid: str, bundle_id: str) -> str: ...
    @abstractmethod
    def f停止应用(self, udid: str, bundle_id: str) -> str: ...
    @abstractmethod
    def f安装IPA(self, udid: str, ipa路径: str) -> str: ...
    @abstractmethod
    def f卸载应用(self, udid: str, bundle_id: str) -> str: ...

    # ---- 截图/崩溃（4）----
    @abstractmethod
    def f截图(self, udid: str, 保存路径: str) -> str: ...
    @abstractmethod
    def f崩溃列表(self, udid: str = '') -> list: ...
    @abstractmethod
    def f拷贝崩溃(self, udid: str, 匹配模式: str, 目标目录: str) -> str: ...
    @abstractmethod
    def f读取崩溃报告(self, udid: str, 崩溃文件: str, 临时目录: str) -> str: ...

    # ---- 状态采集（5）----
    @abstractmethod
    def f抓取日志(self, udid: str = '', 时长秒: float = 6.0, 最大行: int = 200) -> str: ...
    @abstractmethod
    def f采样系统监控(self, udid: str = '', 时长秒: float = 5.0) -> dict: ...
    @abstractmethod
    def f读取电池(self, udid: str = '') -> dict: ...
    @abstractmethod
    def f读取磁盘(self, udid: str = '') -> dict: ...
    @abstractmethod
    def f读取进程(self, udid: str = '') -> list: ...

    # ---- 调试通道（6）----
    @abstractmethod
    def f检查隧道(self) -> list: ...
    @abstractmethod
    def f启动隧道(self) -> str: ...
    @abstractmethod
    def f读取开发者模式(self, udid: str = '') -> str: ...
    @abstractmethod
    def f开启开发者模式(self, udid: str = '') -> str: ...
    @abstractmethod
    def f挂载开发者镜像(self, udid: str = '') -> str: ...
    @abstractmethod
    def f检查镜像(self, udid: str = '') -> list: ...

    # ---- 自检（1）----
    @abstractmethod
    def f执行环境自检(self) -> list: ...
```

工厂：

```python
def f创建后端(b日志回调=None, b配置=None) -> IIosBackend:
    _b选择 = (b配置 or {}).get('ios_backend', 'pymd3')
    from 工具.Ios调试模块.pymd3桥接 import cPymd3设备操作
    from 工具.Ios调试模块.goIos桥接 import cIos设备操作

    if _b选择 == 'goios':
        return cIos设备操作(b日志回调=b日志回调)
    if _b选择 == 'auto':
        _bP = cPymd3设备操作(b日志回调=b日志回调)
        return _bP if _bP.f可用() else cIos设备操作(b日志回调=b日志回调)
    return cPymd3设备操作(b日志回调=b日志回调)   # 默认 pymd3
```

### 5.2 pymd3 桥接（`pymd3桥接.py`）—— 修正版要点

**关键设计**：全部走 subprocess 调 CLI，不 import pymobiledevice3。

```python
# -*- coding: utf-8 -*-
"""pymobiledevice3 后端桥接：仅通过 subprocess 调用 CLI，不 in-process import。"""
import json, os, shutil, subprocess, sys, threading

_bWIN = sys.platform.startswith('win')


def f查找pymd3() -> str:
    """查找 pymobiledevice3 CLI：环境变量 → PATH。"""
    _b环境 = os.environ.get('SUPER_ADB_PYMD3_BIN', '').strip()
    if _b环境 and os.path.isfile(_b环境):
        return _b环境
    _b = shutil.which('pymobiledevice3')
    return _b or ''


class cPymd3错误(Exception):
    pass


class cPymd3设备操作:
    name = 'pymd3'
    display_name = 'pymobiledevice3'

    def __init__(self, b日志回调=None):
        self._b日志回调 = b日志回调
        self._b二进制 = f查找pymd3()
        self._b锁 = threading.Lock()

    # ★ 修正 1：--udid 是【子命令级】选项，必须追加在子命令之后（不是顶层）
    def f构造命令(self, udid, *子命令) -> list:
        _b命令 = [self._b二进制, *[str(x) for x in 子命令]]
        if udid:
            _b命令 += ['--udid', str(udid)]
        return _b命令

    def f运行命令(self, 参数, 超时秒=30.0) -> str:
        if not self.f可用():
            raise cPymd3错误(f安装指引())
        self.f日志('$ ' + ' '.join(参数))
        try:
            _b结果 = subprocess.run(
                参数, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=超时秒,
                creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0)
            _b输出 = (_b结果.stdout or '').strip()
        except subprocess.TimeoutExpired as _b超时:
            # 流式命令超时是预期截流手段，仍回收已产出内容
            _b输出 = ''
            if _b超时.stdout:
                _b输出 = (_b超时.stdout.decode('utf-8', errors='replace')
                          if isinstance(_b超时.stdout, bytes) else str(_b超时.stdout))
            return _b输出
        except FileNotFoundError:
            raise cPymd3错误(f安装指引())
        if _b结果.returncode != 0:
            _b错 = (_b结果.stderr or _b输出 or '未知错误').strip().splitlines()
            raise cPymd3错误(f'pymobiledevice3 失败（{_b结果.returncode}）：'
                             f'{_b错[0] if _b错 else ""}')
        return _b输出

    # ★ 修正 2：停止应用用 pkill --bundle（dvt kill 只接受 PID）
    def f停止应用(self, udid, bundle_id) -> str:
        return self.f运行命令(
            self.f构造命令(udid, 'developer', 'dvt', 'pkill', bundle_id, '--bundle'),
            超时秒=40)

    # ★ 修正 3：检查隧道不能跑 tunneld（它是常驻守护进程，必然超时）
    #   改用 rsd-info --tunnel 探测；探测成功即视为隧道可用
    def f检查隧道(self) -> list:
        try:
            _b文本 = self.f运行命令(
                self.f构造命令('', 'remote', 'rsd-info', '--tunnel', ''), 超时秒=8)
        except cPymd3错误:
            return []
        try:
            _b数据 = json.loads(_b文本)
        except json.JSONDecodeError:
            return [{'raw': _b文本[:200]}] if _b文本 else []
        return _b数据 if isinstance(_b数据, list) else [_b数据]

    # ★ 修正 4：启动隧道 = 后台拉起 tunneld 守护进程（不阻塞 UI）
    def f启动隧道(self) -> str:
        subprocess.Popen(
            self.f构造命令('', 'remote', 'tunneld'),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if _bWIN else 0)
        return 'tunneld 已在后台启动（Windows 需管理员权限）'
```

其余方法按 §5.3 对照表实现；`f执行环境自检` 自检项见 §7。

### 5.3 CLI 命令对照表（修正后）

| 业务方法 | pymobiledevice3 CLI | go-ios 对照 | 备注 |
|---|---|---|---|
| f获取设备列表 | `usbmux list` | `list` | 输出为 JSON 数组（实测 bonjour 侧含 lockdown_info） |
| f获取版本 | `version` | `version` | 返回 CLI 自身版本；iOS 版本从设备信息取 |
| f获取设备信息 | `usbmux list` / `bonjour browse` 的 lockdown_info，或 `developer dvt device-information` | `info` | **待真机实测**确定主用来源（`lockdown info` 是否存在存疑） |
| f获取应用列表 | `apps list`（--user/--system） | `apps --list` | `--no-shutdown` 等参数待实测 |
| f启动应用 | `developer dvt launch <bid>` | `launch <bid>` | 需开发者模式+镜像/隧道 |
| f停止应用 | `developer dvt pkill <bid> --bundle` | `kill <bid>` | **dvt kill 要 PID** |
| f安装IPA | `apps install <ipa>` | `install --path=` | |
| f卸载应用 | `apps uninstall <bid>` | `uninstall <bid>` | |
| f截图 | `developer dvt screenshot <path>` | `screenshot --output=` | 实测 ~0.7s/张 |
| f崩溃列表 | `crash pull <dir>` 后列目录（或 `crash ls`，待实测） | `crash ls` | 批量拉取更稳 |
| f读取崩溃报告 | `crash pull <dir>` + 读文件 | `crash cp` | |
| f抓取日志 | `syslog live`（流式，可 `-m` 过滤） | `syslog` | 更强：含 debug |
| f采样系统监控 | `developer dvt sysmon system`（整机） | `sysmontap` | 进程级用 `sysmon process single/monitor` |
| f读取电池 | `diagnostics battery` | `batterycheck` | |
| f读取磁盘 | 无 1:1；取 `sysmon system` 的 disk 字段 | `diskspace` | 降级返回空 dict + 说明 |
| f读取进程 | `developer dvt sysmon process single`（或 `processes`） | `ps` | 待实测二选一 |
| f检查隧道 | `remote rsd-info --tunnel ''` 探测 | `tunnel ls` | **不可用 tunneld 查询** |
| f启动隧道 | 后台 `remote tunneld`；iOS 17.4+ 亦可 `lockdown start-tunnel` | `tunnel start` | Win 需管理员 |
| f读取/开启开发者模式 | `amfi`（查询/enable-developer-mode） | `devmode get/enable` | 查询子命令名待实测 |
| f挂载开发者镜像 | `mounter auto-mount` | `image auto` | **不是 `mounter auto`** |
| f检查镜像 | `mounter list`（待实测） | `image list` | |
| （扩展）代理/证书 | `profile install-http-proxy` / `profile install <证书路径>`（**无 `install-ssl-cert` 子命令**，证书走 `install`） | — | pymd3 独有 |
| （扩展）oslog | `developer dvt oslog` | — | pymd3 独有 |
| （扩展）KDebug | `developer dvt core-profile-session parse-live` | — | **不是 `kdump`** |
| （扩展）沙盒文件 | `apps afc` / `afc shell` | — | pymd3 独有 |

### 5.4 三个最容易踩的坑（务必记住）

1. **`--udid` 位置**：pmd3 是子命令级选项 → `pymobiledevice3 apps list --udid X`；
   go-ios 才是顶层 → `ios --udid=X list`。两者**不可互换**。
2. **`dvt kill` 只接受 PID**：按 bundle 停止用 `dvt pkill <expr> --bundle`，或 `dvt process-id-for-bundle-id <bid>` 拿 PID 再 kill。
3. **`tunneld` 是守护进程**：启动后常驻不退出，任何"把它当查询命令 + 超时"的写法都必然失败。

---

## 6. 推→拉阻抗转换

iOS 侧 `syslog live` / `dvt sysmon` 是流式输出，处理方式与现有 go-ios 实现一致：

- **抓取一段（f抓取日志 / f采样系统监控）**：`subprocess.run(timeout=N)` 或 `Popen + readline` 定时截断，取最近 N 行/最后一帧。
- **日志跟随（iOS日志对话框）**：`Popen` 常驻 + 后台线程逐行入队 + 主线程 `QTimer`（200ms）批量追加，避免高频信号打爆 UI；上限 8000 行滚动裁剪。
- **stop()**：kill 子进程、清空缓存。

pymd3 优势：流式输出为逐行 ndjson，解析比 go-ios sysmontap 文本流稳定。

---

## 7. 部署前置与环境自检项

| 平台 | 依赖 | 说明 |
|---|---|---|
| Windows | iTunes（Store 版）+ pymd3 +（3.13+）VS C++ Build Tools | iOS 17.0–17.3.1 需额外驱动；隧道需管理员 |
| Linux | `usbmuxd` + `libusb-1.0-0-dev` + pymd3 | 隧道需 root 或 udev 规则 |
| macOS | `brew install libusb openssl` + pymd3 | 17.4+ 用 lockdown tunnel；旧版需 sudo |

**环境自检面板检测项**（`f执行环境自检` 返回 `[{名称, 状态, 信息, 指引}]`，状态 ok/bad/warn/none）：

1. pymobiledevice3 CLI 是否存在（PATH / `SUPER_ADB_PYMD3_BIN`）→ 缺失给安装指引
2. 版本号（与 11.10.3 比对，warn 提示版本漂移）
3. **MSVC/lzfse 就绪**（仅 Windows 且 Python ≥3.13）：vswhere 查询 + 自定义路径兜底 → 缺失给 Build Tools 下载链接
4. **iTunes / Apple Mobile Device Support 驱动**（Windows）
5. 设备枚举（0 台 → warn：连接并信任此电脑）
6. 隧道可达性（`remote rsd-info --tunnel`）
7. 开发者模式（`amfi` 查询）
8. 开发者镜像（`mounter list`）

**设备侧一次性准备**：信任此电脑 → 开发者模式（设置→隐私与安全性，重启一次）→ iOS 17+ 建隧道 → 挂载开发者镜像。

---

## 8. 无真机联调（模拟器）—— 换后端最容易漏的一环

现有 `goIos模拟器.py` 模拟的是 **go-ios CLI 协议**，换 pymd3 后**不能直接用**。两条路：

| 方案 | 做法 | 优劣 |
|---|---|---|
| **A. CLI 协议 stub（推荐）** | 新增 `pymd3模拟器.py`，按 §5.3 对照表模拟各子命令的 stdout（JSON/文本），`SUPER_ADB_IOS_MOCK=1` 时桥接把"二进制"换成 `[python, pymd3模拟器.py]` | 与现有一致、可验证完整解析链路；需维护一份 stub |
| B. 桥接层内短路 | 桥接方法检测到 mock 环境变量直接返回写死样例（不起子进程） | 更快更省；但**绕过了解析层**，无法验证解析逻辑，且日志跟随对话框要单独改造 |

**推荐 A**，并保留一条约束：`syslog live` / `sysmon` 必须输出**流式**（持续打印 + flush），否则"抓取/跟随"两条链路验证不到。

切换开关（沿用现有约定）：

- `SUPER_ADB_IOS_MOCK=1` → 用模拟器
- 取消该变量 → 回到真实 pymd3 CLI，模拟器不参与任何生产路径

---

## 9. 路线图

| 阶段 | 目标 | 交付物 | 周期 |
|---|---|---|---|
| **P0 装通** | 系统 Python 装上 pymd3 11.10.3 | 安装成功 + `pymobiledevice3 --help` 通过 | 0.5 天（含 Build Tools） |
| **P1 Spike** | 无真机也能固化命令契约 | `pymd3模拟器.py` + 桥接骨架 + 3 条命令跑通（list / 设备信息 / screenshot） | 1~2 天 |
| P2 桥接完整 | 25+3 方法全覆盖，UI 零改动 | `pymd3桥接.py` + `后端工厂.py` + 主入口改造 | 3~5 天 |
| P3 真机实测 | 固化 JSON 字段别名表（尤其 sysmon system） | `pymd3命令映射.py` + 别名表 | 1~2 天（需真机） |
| P4 三平台同步 | Win/Mac/Linux md5 一致 + 编译校验 | 同步脚本/校验 | 0.5 天 |
| P5 pymd3 独有能力 | 代理/证书、oslog、KDebug、沙盒、备份 | 独立面板，按需启用 | 后续 |

---

## 10. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| **GPL 边界** | 闭源商用可能被要求开源 | 源码 MIT + CLI 子进程；不打 pymd3 进 exe；商用前法务复核 |
| **lzfse 需编译（Python 3.13+）** | 用户 `pip install` 失败 | 装 VS C++ Build Tools；或用 ≤3.12 吃现成 wheel；或最小集跳过 pyimg4 |
| 部分命令名未实测 | 解析失败/命令不存在 | P1 用模拟器固化；P3 真机复核；所有存疑项在 §5.3 已标注 |
| **`IIosBackend` 方法不齐** | 后端切换 AttributeError | §5.1 已固定 25+3 方法清单，两后端必须同时满足 |
| **模拟器需按新协议重写** | 无真机时 UI 链路无法验证 | §8 方案 A，随桥接同批交付 |
| pymd3 CLI 字段随版本变 | 解析失败 | 锁 11.10.3 + 别名表 + 字段缺失容错 + 自检显示版本 |
| Windows 隧道需管理员 | 用户体验 | 自检引导 + 降级到非隧道功能 |
| 用户没装 pymd3 | 功能不可用 | 自检红灯 + 一键安装指引 + 可回退 go-ios |
| 打包误收 pymd3 依赖 | 体积膨胀 + GPL | §2.2 excludes + CI 产物体积检查 |
| 全量装依赖 ~180 MB | 用户磁盘/安装时间 | §2.5 最小集压到 ~80–90 MB |

---

## 11. 决策记录

| 维度 | go-ios | pymd3（选定） |
|---|---|---|
| 许可证 | MIT 干净 | GPL-3.0，需进程边界隔离 |
| 打包体积 | +10~20 MB（带 ios.exe） | ≈0（用户自装） |
| 能力 | 基础调试够用 | 最全：oslog/KDebug/代理证书/沙盒/备份/WebInspector/PCAP |
| iOS 17+ 隧道 | Win 需 wintun+管理员 | tunneld 守护进程，macOS 可免 root |
| 已有代码 | `goIos桥接.py` 已完整 | 需新写 `pymd3桥接.py`（同构 25+3 方法） |
| 安装门槛 | 下载单 exe | pip 装 ~90 包；Win/3.13+ 需 Build Tools |

**最终决策（2026-09-09）**：iOS 后端**整套切换为 pymobiledevice3**。
`goIos桥接.py` 与 `goIos模拟器.py` 保留为**回退/对照实现**，配置项 `ios_backend` 可切，
后续所有 iOS 新能力（代理设置、证书、沙盒、oslog 等）一律基于 pymd3 实现。
