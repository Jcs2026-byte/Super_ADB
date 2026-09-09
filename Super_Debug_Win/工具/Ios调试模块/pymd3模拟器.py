# -*- coding: utf-8 -*-
"""
工具 / Ios调试模块 / pymd3模拟器.py
====================================
pymobiledevice3 开发模拟器（STUB，仅供无真机时联调 UI / 桥接解析链路）。

启用方式：设置环境变量 SUPER_ADB_IOS_MOCK=1 后启动主程序，
桥接层自动以「python pymd3模拟器.py <args…>」代替真实 pymobiledevice3。
关闭方式：取消环境变量即可回到真实后端，模拟器不参与任何生产路径。

行为约定（输出形态逐条对齐 pymobiledevice3 11.x 真实 CLI）：
    - usbmux list          → JSON 数组（lockdown short_info 形态）
    - version              → 纯文本版本号
    - lockdown info        → JSON 对象（lockdown all_values 形态）
    - apps list            → JSON 对象，{bundleId: {…}}（不是数组！）
    - apps install/uninstall → 无输出，退出码 0
    - developer dvt launch / pkill → 纯文本
    - developer screenshot <路径>   → 写 PNG，无输出
    - crash ls             → 逐行纯文本（不是 JSON）
    - crash pull <目录>    → 在目录下落盘 .ips
    - syslog live          → 流式持续输出（直到被外部超时截断/kill）
    - developer dvt sysmon system → 一次性输出「键: 值」纯文本
    - diagnostics battery single → JSON 对象
    - processes ps         → JSON 对象，{pid: {ProcessName: …}}
    - amfi developer-mode-status → JSON 布尔
    - mounter list         → JSON 数组
    - profile list         → JSON 数组（描述文件元数据）
    - profile install-http-proxy → 纯文本
    - profile remove-http-proxy → 纯文本
    - profile install <路径> → 校验文件存在，纯文本
    其余子命令 → 简单文本。

命名规范（新建代码全遵守）：私有函数 _f 前缀、私有变量 _b 前缀、
公开函数 f 前缀；均为「前缀 + 中文词」，前缀后不再加下划线。
"""
import json
import os
import struct
import sys
import time
import zlib

_b默认udid = 'MOCK-0000-0000-0000-000000000001'
_b版本号 = '11.10.3'

# 模拟设备
_b设备表 = [
    {
        'Identifier': 'MOCK-AAAA-1111-2222-333344445555',
        'UniqueDeviceID': 'MOCK-AAAA-1111-2222-333344445555',
        'DeviceName': '模拟 iPhone 15 Pro',
        'ProductType': 'iPhone16,1',
        'ProductVersion': '18.0',
        'BuildVersion': '22A999-mock',
        'DeviceClass': 'iPhone',
        'ConnectionType': 'USB',
    },
    {
        'Identifier': 'MOCK-BBBB-6666-7777-888899990000',
        'UniqueDeviceID': 'MOCK-BBBB-6666-7777-888899990000',
        'DeviceName': '模拟 iPad Air',
        'ProductType': 'iPad13,16',
        'ProductVersion': '17.5',
        'BuildVersion': '21F999-mock',
        'DeviceClass': 'iPad',
        'ConnectionType': 'USB',
    },
]

_b崩溃表 = [
    'JetsamEvent-2026-09-09-092233.ips',
    'DemoApp-2026-09-08-113042.ips',
]


def f帮助():
    print(f'pymobiledevice3 (MOCK {_b版本号}) - SUPER_ADB_IOS_MOCK=1 模拟器')
    print('模拟命令组：usbmux list / version / lockdown info / apps list|install|uninstall')
    print('            developer screenshot / developer dvt launch|pkill|sysmon')
    print('            crash ls|pull / syslog live / diagnostics battery')
    print('            processes ps / amfi / mounter / remote tunneld')
    print('            profile list|install-http-proxy|remove-http-proxy|install')


def f分离udid(_b参数):
    """剥离 --udid / --udid=，返回 (udid, 剩余参数)。"""
    _budid = ''
    _b剩余 = []
    _b跳过下一个 = False
    for _b索引, _b项 in enumerate(_b参数):
        if _b跳过下一个:
            _b跳过下一个 = False
            continue
        if _b项 == '--udid':
            _budid = _b参数[_b索引 + 1] if _b索引 + 1 < len(_b参数) else ''
            _b跳过下一个 = True
            continue
        if _b项.startswith('--udid='):
            _budid = _b项[len('--udid='):]
            continue
        _b剩余.append(_b项)
    return (_budid or _b默认udid), _b剩余


# ----------------------------------------------------------------------
# 内置占位 PNG（128×128 渐变，避免依赖第三方库）
# ----------------------------------------------------------------------
def f生成占位png(_b保存路径, _b宽度=128, _b高度=128):
    """手写 PNG（无第三方依赖）：逐像素渐变占位图。"""

    def _f写块(_b类型, _b数据):
        _b头 = _b类型 + _b数据
        _b校验 = struct.pack('>I', zlib.crc32(_b头) & 0xffffffff)
        return struct.pack('>I', len(_b数据)) + _b头 + _b校验

    _b像素行 = bytearray()
    for _b行 in range(_b高度):
        _b像素行.append(0)  # filter None
        for _b列 in range(_b宽度):
            _b像素行.append((_b行 * 255) // _b高度)          # R
            _b像素行.append((_b列 * 255) // _b宽度)          # G
            _b像素行.append(((_b行 + _b列) * 255) // (_b高度 + _b宽度))  # B
    _b信息头 = struct.pack('>IIBBBBB', _b宽度, _b高度, 8, 2, 0, 0, 0)
    _b图片 = (b'\x89PNG\r\n\x1a\n'
              + _f写块(b'IHDR', _b信息头)
              + _f写块(b'IDAT', zlib.compress(bytes(_b像素行), 6))
              + _f写块(b'IEND', b''))
    with open(_b保存路径, 'wb') as _b文件流:
        _b文件流.write(_b图片)
    return _b保存路径


# ----------------------------------------------------------------------
# 各子命令响应
# ----------------------------------------------------------------------
def f设备列表():
    return json.dumps(_b设备表, ensure_ascii=False)


def f设备信息(_budid):
    for _b设备 in _b设备表:
        if _b设备['UniqueDeviceID'] == _budid:
            return json.dumps(_b设备, ensure_ascii=False)
    _b基础 = dict(_b设备表[0])
    _b基础['UniqueDeviceID'] = _budid
    _b基础['Identifier'] = _budid
    return json.dumps(_b基础, ensure_ascii=False)


def f应用列表():
    # 真实 pymobiledevice3 返回 {bundleId: {…}}，模拟器保持同构以检验桥接的摊平逻辑
    return json.dumps({
        'com.apple.mobilesafari': {'CFBundleName': 'Safari',
                                   'CFBundleDisplayName': 'Safari',
                                   'CFBundleShortVersionString': '18.0',
                                   'ApplicationType': 'System'},
        'com.apple.Preferences': {'CFBundleName': 'Preferences',
                                  'CFBundleDisplayName': '设置',
                                  'CFBundleShortVersionString': '18.0',
                                  'ApplicationType': 'System'},
        'com.apple.calculator': {'CFBundleName': 'Calculator',
                                 'CFBundleDisplayName': '计算器',
                                 'CFBundleShortVersionString': '18.0',
                                 'ApplicationType': 'System'},
        'com.example.demo': {'CFBundleName': 'DemoApp',
                             'CFBundleDisplayName': '示例App',
                             'CFBundleShortVersionString': '1.0.2',
                             'ApplicationType': 'User'},
    }, ensure_ascii=False)


def f崩溃列表():
    """crash ls → 逐行纯文本（对齐真实 CLI，非 JSON）。"""
    return '\n'.join(_b崩溃表)


def f崩溃内容(_b文件名):
    return (
        '{"app_name":"DemoApp","timestamp":"2026-09-09 09:22:33.00 +0800",'
        '"termination":{"indicator":"Jetsam","byPid":1,"code":0},'
        '"exception":{"type":"EXC_RESOURCE"}}\n'
        f'----- 模拟 {_b文件名}（OOM）崩溃报告内容 -----\n'
        'reason: memorystatus_kill_on_demand\n'
        '说明：该记录为模拟数据，用于真机前联调崩溃查看链路。\n'
    )


def f拷贝崩溃(_b目标目录, _b匹配=None):
    """crash pull <目录> [--match 正则]：把匹配的 .ips 落盘到目标目录。"""
    _b命中 = list(_b崩溃表)
    if _b匹配:
        import re
        try:
            _b正则 = re.compile(_b匹配)
            _b命中 = [x for x in _b崩溃表 if _b正则.search(os.path.basename(x))]
        except re.error:
            _b命中 = [x for x in _b崩溃表 if _b匹配 in x]
    os.makedirs(_b目标目录, exist_ok=True)
    for _b文件名 in _b命中:
        with open(os.path.join(_b目标目录, _b文件名), 'w', encoding='utf-8') as _b文件流:
            _b文件流.write(f崩溃内容(_b文件名))
    return f'pulled {len(_b命中)} crash report(s) to {_b目标目录}'


def f系统日志(_budid):
    """流式输出模拟日志；外部会在数秒后超时截断。"""
    _b序号 = 0
    try:
        while True:
            _b序号 += 1
            print(f'2026-09-09 10:00:0{_b序号 % 10} {_budid} '
                  f'SpringBoard (pid:{1000 + _b序号}) [mock] 前台应用切换 '
                  f'com.apple.mobilesafari 序号={_b序号}', flush=True)
            time.sleep(0.02)
    except BrokenPipeError:
        pass


def f系统监控():
    """developer dvt sysmon system → 一次性「键: 值」纯文本。"""
    _b行 = [
        'CPUCount: 6',
        'EnabledCPUs: 6',
        'CPU_TotalLoad: 18.5',
        'CPU_UserLoad: 11.2',
        'CPU_SystemLoad: 6.1',
        'CPU_NiceLoad: 1.2',
        'SystemCPUUsage: 18.5',
        'vm_free_count: 81234',
        'vm_active_count: 120456',
        'vm_inactive_count: 65432',
        'vm_wire_count: 98765',
        'vm_page_size: 16384',
    ]
    return '\n'.join(_b行)


def f电池():
    return json.dumps({
        'Status': 'Success',
        'Payload': {
            'BatteryCurrentCapacity': 82,
            'BatteryIsCharging': False,
            'ExternalConnected': False,
            'BatteryVoltage': 3.85,
            'BatteryTemperature': 34.5,
        },
    }, ensure_ascii=False)


def f进程():
    # 真实 pymobiledevice3 返回 {pid: {ProcessName: …}}
    return json.dumps({
        '1': {'ProcessName': 'launchd'},
        '1000': {'ProcessName': 'SpringBoard'},
        '4242': {'ProcessName': 'DemoApp'},
        '5678': {'ProcessName': 'mobilesafari'},
    }, ensure_ascii=False)


def f镜像列表():
    return json.dumps([{'ImageSignature': 'mock-signature',
                        'ImageType': 'Developer',
                        'ImagePath': '/Developer/DeveloperDiskImage-18.0.dmg'}],
                      ensure_ascii=False)


def f描述文件列表():
    """profile list → JSON 数组（真实 CLI 返回描述文件元数据数组）。"""
    return json.dumps([
        {'PayloadIdentifier': 'com.apple.proxy.http.global.mocked',
         'PayloadDisplayName': 'Global HTTP Proxy',
         'PayloadType': 'com.apple.proxy.http.global',
         'PayloadVersion': 1,
         'ProxyServer': '192.168.1.10',
         'ProxyServerPort': 8888,
         'PayloadUUID': 'MOCK-GLOBAL-HTTP-PROXY-UUID'},
    ], ensure_ascii=False)


def f安装HTTP代理(_b服务器, _b端口):
    """profile install-http-proxy → 记录代理并返回成功文本。"""
    return f'HTTP proxy profile installed: {_b服务器}:{_b端口} (mock)'


def f移除HTTP代理():
    """profile remove-http-proxy → 返回移除成功文本。"""
    return 'HTTP proxy profile removed (mock)'


def f安装描述文件(_b路径):
    """profile install → 校验文件存在后返回成功文本。"""
    if not _b路径 or not os.path.isfile(_b路径):
        print(json.dumps({'error': f'file not found: {_b路径}'}, ensure_ascii=False),
              file=sys.stderr)
        return None
    return f'profile installed: {_b路径} (mock)'


def f未知命令(_b参数):
    print(json.dumps({'error': f'unknown command: {_b参数}'}, ensure_ascii=False))
    return 1


# ----------------------------------------------------------------------
# 入口分发
# ----------------------------------------------------------------------
def f主入口(_b参数):
    """按 pymobiledevice3 命令行结构分发（返回进程退出码）。"""
    _budid, _b剩余 = f分离udid(list(_b参数))
    if not _b剩余:
        f帮助()
        return 0

    _b组 = _b剩余[0]
    _b尾 = _b剩余[1:]
    _b子 = _b尾[0] if _b尾 else ''

    try:
        # ---------------- 顶层 ----------------
        if _b组 == 'version':
            print(_b版本号)

        elif _b组 == 'usbmux' and _b子 == 'list':
            print(f设备列表())

        elif _b组 == 'lockdown' and _b子 == 'info':
            print(f设备信息(_budid))

        # ---------------- apps ----------------
        elif _b组 == 'apps':
            if _b子 == 'list':
                print(f应用列表())
            elif _b子 == 'install':
                # 真实 CLI 无输出；仅校验文件存在
                _b包路径 = _b尾[1] if len(_b尾) > 1 else ''
                if _b包路径 and not os.path.isfile(_b包路径):
                    print(json.dumps({'error': f'file not found: {_b包路径}'}), file=sys.stderr)
                    return 1
            elif _b子 == 'uninstall':
                pass
            else:
                return f未知命令(_b尾)

        # ---------------- developer ----------------
        elif _b组 == 'developer':
            if _b子 == 'screenshot':
                _b输出 = _b尾[1] if len(_b尾) > 1 else os.path.join(os.getcwd(), 'pmd3_shot.png')
                f生成占位png(_b输出)
            elif _b子 == 'dvt':
                _bdvt子 = _b尾[1] if len(_b尾) > 1 else ''
                if _bdvt子 == 'launch':
                    print(f'launched {_b尾[2] if len(_b尾) > 2 else ""} (mock)')
                elif _bdvt子 == 'pkill':
                    print(f'killed {_b尾[2] if len(_b尾) > 2 else ""} (mock)')
                elif _bdvt子 == 'sysmon':
                    print(f系统监控())
                elif _bdvt子 == 'screenshot':
                    _b输出 = _b尾[2] if len(_b尾) > 2 else os.path.join(os.getcwd(), 'pmd3_shot.png')
                    f生成占位png(_b输出)
                else:
                    return f未知命令(_b尾[1:])
            else:
                return f未知命令(_b尾)

        # ---------------- crash ----------------
        elif _b组 == 'crash':
            if _b子 == 'ls':
                print(f崩溃列表())
            elif _b子 == 'pull':
                _b目录 = _b尾[1] if len(_b尾) > 1 else os.getcwd()
                _b匹配 = None
                for _b索引, _b项 in enumerate(_b尾):
                    if _b项 == '--match' and _b索引 + 1 < len(_b尾):
                        _b匹配 = _b尾[_b索引 + 1]
                    elif _b项.startswith('--match='):
                        _b匹配 = _b项[len('--match='):]
                print(f拷贝崩溃(_b目录, _b匹配))
            else:
                return f未知命令(_b尾)

        # ---------------- syslog ----------------
        elif _b组 == 'syslog' and _b子 == 'live':
            f系统日志(_budid)

        # ---------------- diagnostics ----------------
        elif _b组 == 'diagnostics':
            if _b子 == 'battery' and len(_b尾) > 1 and _b尾[1] == 'single':
                print(f电池())
            else:
                return f未知命令(_b尾)

        # ---------------- processes ----------------
        elif _b组 == 'processes' and _b子 == 'ps':
            print(f进程())

        # ---------------- amfi ----------------
        elif _b组 == 'amfi':
            if _b子 == 'developer-mode-status':
                print(json.dumps(True))
            elif _b子 == 'enable-developer-mode':
                print('Developer Mode enable requested (mock)')
            else:
                return f未知命令(_b尾)

        # ---------------- mounter ----------------
        elif _b组 == 'mounter':
            if _b子 == 'list':
                print(f镜像列表())
            elif _b子 == 'auto-mount':
                print('Developer image mounted (mock)')
            else:
                return f未知命令(_b尾)

        # ---------------- remote ----------------
        elif _b组 == 'remote':
            if _b子 == 'tunneld':
                print('tunneld started (mock)')
            elif _b子 == 'rsd-info':
                print(json.dumps({'UDID': _budid, 'mock': True}, ensure_ascii=False))
            else:
                return f未知命令(_b尾)

        # ---------------- profile ----------------
        elif _b组 == 'profile':
            if _b子 == 'list':
                print(f描述文件列表())
            elif _b子 == 'install-http-proxy':
                _b服务器 = _b尾[1] if len(_b尾) > 1 else '192.168.1.10'
                _b端口 = _b尾[2] if len(_b尾) > 2 else '8888'
                print(f安装HTTP代理(_b服务器, _b端口))
            elif _b子 == 'remove-http-proxy':
                print(f移除HTTP代理())
            elif _b子 == 'install':
                _b路径 = _b尾[1] if len(_b尾) > 1 else ''
                _b输出 = f安装描述文件(_b路径)
                if _b输出 is None:
                    return 1
                print(_b输出)
            else:
                return f未知命令(_b尾)

        else:
            return f未知命令(_b剩余)
    except BrokenPipeError:
        pass
    except Exception as _b异常:  # noqa: BLE001 —— mock 兜底，任何异常转 JSON error
        print(json.dumps({'error': f'mock error: {_b异常}'}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(f主入口(sys.argv[1:]))
