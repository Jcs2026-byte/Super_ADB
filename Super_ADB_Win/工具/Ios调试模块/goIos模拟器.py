# -*- coding: utf-8 -*-
"""
工具 / Ios调试模块 / goIos模拟器.py
====================================
go-ios 开发模拟器（STUB，仅供无真机时联调 UI / 桥接解析链路）。

启用方式：设置环境变量 SUPER_ADB_IOS_MOCK=1 后启动主程序，
桥接层自动以「python goIos模拟器.py <args…>」代替真实 ios 二进制。
关闭方式：取消环境变量即可回到真实 go-ios 二进制，模拟器不参与任何生产路径。

行为约定（尽量贴近 go-ios 真实输出形态）：
    - list / version / info / apps / crash ls / batterycheck / diskspace / ps
      → stdout JSON（与 go-ios 默认 JSON 输出一致）
    - launch / kill / install / uninstall / image auto / devmode enable /
      tunnel start / crash cp → 简单文本
    - syslog / sysmontap → 流式持续输出（直到被外部超时截断/kill）
    - screenshot --output=<路径> → 写一张内置占位 PNG 到该路径
    - crash cp <pattern> <dir> → 在 <dir> 落盘模拟 .ips 供详情读取
（本文件命名遵守 c/f/b 前缀规范 —— 顶层入口用 f_main，内部变量 _b 前缀。）
"""
import json
import os
import sys
import time
import zlib
import struct

# 无参数也能被 -h 帮助触发，正常打印帮助
def f_帮助():
    print('ios (go-ios MOCK) - Super_ADB_IOS_MOCK=1 模拟器')
    print('模拟子命令：list/version/info/apps/launch/kill/install/uninstall')
    print('            screenshot/crash ls/crash cp/syslog/sysmontap')
    print('            batterycheck/diskspace/ps/devmode/image/tunnel')


def f_取_udid(_b参数):
    """从命令行提取 --udid= 值（未指定返回空）。"""
    for _b参数项 in _b参数:
        if _b参数项.startswith('--udid='):
            return _b参数项[len('--udid='):]
    return 'MOCK-0000-0000-0000-000000000001'


# ----------------------------------------------------------------------
# 内置占位 PNG（128×128 蓝绿渐变，避免依赖第三方库）
# ----------------------------------------------------------------------
def f_生成_占位png(_b保存路径, _b宽度=128, _b高度=128):
    """手写 PNG（无第三方依赖）：逐行纯色渐变。"""
    def _f_chunk(_b类型, _b数据):
        _b_头 = _b类型 + _b数据
        _b_校验 = struct.pack('>I', zlib.crc32(_b_头) & 0xffffffff)
        return struct.pack('>I', len(_b_数据)) + _b_头 + _b_校验

    _b行们 = bytearray()
    for _b行 in range(_b_高度):
        _b行们.append(0)  # filter None
        for _b列 in range(_b_宽度):
            _b行们.append((_b行 * 255) // _b_高度)          # R
            _b行们.append((_b列 * 255) // _b_宽度)          # G
            _b行们.append(((_b行 + _b_列) * 255) // (_b_高度 + _b_宽度))  # B
    _b_ihdr = struct.pack('>IIBBBBB', _b_宽度, _b_高度, 8, 2, 0, 0, 0)
    _b_png = (b'\x89PNG\r\n\x1a\n'
              + _f_chunk(b'IHDR', _b_ihdr)
              + _f_chunk(b'IDAT', zlib.compress(bytes(_b行们), 6))
              + _f_chunk(b'IEND', b''))
    with open(_b_保存路径, 'wb') as _b文件流:
        _b文件流.write(_b_png)
    return _b保存路径


# ----------------------------------------------------------------------
# 各子命令响应
# ----------------------------------------------------------------------
def f_list():
    return json.dumps([
        {'udid': 'MOCK-AAAA-1111-2222-333344445555',
         'name': '模拟 iPhone 15 Pro', 'ProductVersion': '18.0',
         'activationState': 'Activated'},
        {'udid': 'MOCK-BBBB-6666-7777-888899990000',
         'name': '模拟 iPad Air', 'ProductVersion': '17.5',
         'activationState': 'Activated'},
    ])


def f_version():
    return json.dumps({'version': 'v1.2.0-mock', 'go-ios': 'MOCK'})


def f_info(_budid):
    return json.dumps({
        'DeviceName': '模拟 iPhone 15 Pro' if _budid.startswith('MOCK-AAAA') else '模拟 iPad Air',
        'ProductType': 'iPhone16,1' if _budid.startswith('MOCK-AAAA') else 'iPad13,16',
        'ProductVersion': '18.0' if _budid.startswith('MOCK-AAAA') else '17.5',
        'BuildVersion': '22A999-mock',
        'SerialNumber': 'MOCK-SERIAL-0001',
        'WiFiAddress': 'AA:BB:CC:DD:EE:01',
        'BluetoothAddress': 'AA:BB:CC:DD:EE:02',
        'CPUArchitecture': 'arm64e',
        'RegionInfo': 'CN/A',
    })


def f_apps():
    _b应用 = [
        {'bundleID': 'com.apple.mobilesafari', 'name': 'Safari', 'version': '18.0'},
        {'bundleID': 'com.apple.Preferences', 'name': '设置', 'version': '18.0'},
        {'bundleID': 'com.apple.calculator', 'name': '计算器', 'version': '18.0'},
        {'bundleID': 'com.example.demo', 'name': '示例App', 'version': '1.0.2'},
    ]
    return json.dumps(_b应用)


def f_launch(_budid, _b_bundle):
    return json.dumps({'pid': 4242, 'bundleID': _b_bundle, 'udid': _budid})


def f_kill(_budid, _b_bundle):
    return json.dumps({'killed': _b_bundle, 'udid': _budid})


def f_install(_budid, _b路径):
    return json.dumps({'installed': os.path.basename(_b路径), 'udid': _budid})


def f_uninstall(_budid, _b_bundle):
    return json.dumps({'uninstalled': _b_bundle, 'udid': _budid})


def f_screenshot(_budid, _b输出路径):
    f_生成_占位png(_b输出路径)
    return json.dumps({'filename': _b输出路径})


def f_crash_ls():
    return json.dumps([
        'JetsamEvent-2026-09-09-092233.ips',
        'DemoApp-2026-09-08-113042.ips',
    ])


def f_crash_cp(_b匹配, _b目标目录):
    """模拟把崩溃文件拷贝到本机目录，方便 f读取崩溃报告 读回。"""
    if _b匹配 in ('*', '*ips*', '*ips'):
        _b文件名 = 'JetsamEvent-2026-09-09-092233.ips'
    else:
        _b文件名 = os.path.basename(str(_b匹配))
    _b内容 = (
        '{"app_name":"DemoApp","timestamp":"2026-09-09 09:22:33.00 +0800",'
        '"termination":{"indicator":"Jetsam","byPid":1,"code":0},'
        '"exception":{"type":"EXC_RESOURCE"}}\n'
        '----- 模拟 JetsamEvent（OOM）崩溃报告内容 -----\n'
        'reason: memorystatus_kill_on_demand\n'
        '说明：该记录为模拟数据，用于真机前联调崩溃查看链路。\n'
    )
    with open(os.path.join(_b目标目录, _b文件名), 'w', encoding='utf-8') as _b文件流:
        _b文件流.write(_b内容)
    return json.dumps({'copied': [_b文件名], 'to': _b目标目录})


def f_syslog(_budid):
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


def f_sysmontap(_budid):
    """流式输出 sysmontap 帧；桥接层读取数秒后取最近一帧。"""
    _b序号 = 0
    try:
        while True:
            _b序号 += 1
            _b帧 = {
                'ts': time.strftime('%H:%M:%S'),
                'cpu_pct': round(12 + (_b序号 % 20), 1),
                'per_core': {str(_b核): round(5 + _b序号 % 40, 1)
                             for _b核 in range(8)},
                'mem_used_mb': round(3200 + _b序号 % 50, 1),
                'mem_total_mb': 7800,
                'batt_temp': 34.5,
                'seq': _b序号,
            }
            print(json.dumps(_b帧), flush=True)
            time.sleep(0.5)
    except BrokenPipeError:
        pass


def f_batterycheck():
    return json.dumps({
        'Level': 0.82, 'Charging': False, 'State': 'Unplugged',
        'Voltage': 3.85, 'Temperature': 34.5,
    })


def f_diskspace():
    return json.dumps({'Total': 128_000_000_000,
                       'Free': 62_300_000_000,
                       'TotalData': 128_000_000_000})


def f_ps():
    return json.dumps([
        {'pid': 1, 'name': 'launchd'},
        {'pid': 1000, 'name': 'SpringBoard'},
        {'pid': 4242, 'name': 'DemoApp'},
        {'pid': 5678, 'name': 'mobilesafari'},
    ])


def f_devmode_get():
    return 'Developer Mode: enabled'


def f_devmode_enable():
    return 'Developer Mode enable requested (mock)'


def f_image_list():
    return json.dumps(['DeveloperDiskImage-18.0.dmg'])


def f_image_auto():
    return 'Developer image mounted (mock)'


def f_tunnel_ls():
    return json.dumps([{'udid': 'MOCK-AAAA-1111-2222-333344445555',
                        'address': '127.0.0.1', 'rsd': 49152}])


def f_tunnel_start():
    return 'Tunnel started (mock)'


def f_未知(_b参数):
    print(json.dumps({'error': f'unknown command: {_b参数}'}))
    return 1


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def f_main(_b参数):
    """按 go-ios 命令行结构分发（返回进程退出码）。"""
    _b参数 = list(_b参数)
    # 丢弃全局 --udid= 并记录
    _budid = ''
    _b剩余 = []
    for _b项 in _b参数:
        if _b项.startswith('--udid='):
            _budid = _b项[len('--udid='):]
        else:
            _b剩余.append(_b项)
    if not _b剩余:
        f_帮助()
        return 0
    _b命令 = _b剩余[0]
    _b尾参 = _b剩余[1:]
    try:
        if _b命令 == 'list':
            print(f_list())
        elif _b命令 == 'version':
            print(f_version())
        elif _b命令 == 'info':
            print(f_info(_budid))
        elif _b命令 == 'apps':
            print(f_apps())
        elif _b命令 == 'launch':
            print(f_launch(_budid, _b尾参[0] if _b尾参 else ''))
        elif _b命令 == 'kill':
            print(f_kill(_budid, _b尾参[0] if _b尾参 else ''))
        elif _b命令 == 'install':
            print(f_install(_budid, _b尾参[0] if _b尾参 else ''))
        elif _b命令 == 'uninstall':
            print(f_uninstall(_budid, _b尾参[0] if _b尾参 else ''))
        elif _b命令 == 'screenshot':
            _b输出 = ''
            for _b尾 in _b尾参:
                if _b尾.startswith('--output='):
                    _b输出 = _b尾[len('--output='):]
            if not _b输出:
                _b输出 = os.path.join(os.getcwd(), 'ios_screenshot_mock.png')
            print(f_screenshot(_budid, _b输出))
        elif _b命令 == 'crash':
            if _b尾参 and _b尾参[0] == 'ls':
                print(f_crash_ls())
            elif _b尾参 and _b尾参[0] == 'cp':
                _b匹配 = _b尾参[1] if len(_b尾参) > 1 else '*'
                _b目录 = _b尾参[2] if len(_b尾参) > 2 else os.getcwd()
                print(f_crash_cp(_b匹配, _b目录))
            else:
                return f_未知(_b尾参)
        elif _b命令 == 'syslog':
            f_syslog(_budid)
        elif _b命令 == 'sysmontap':
            f_sysmontap(_budid)
        elif _b命令 == 'batterycheck':
            print(f_batterycheck())
        elif _b命令 == 'diskspace':
            print(f_diskspace())
        elif _b命令 == 'ps':
            print(f_ps())
        elif _b命令 == 'devmode':
            if _b尾参 and _b尾参[0] == 'enable':
                print(f_devmode_enable())
            else:
                print(f_devmode_get())
        elif _b命令 == 'image':
            if _b尾参 and _b尾参[0] == 'auto':
                print(f_image_auto())
            else:
                print(f_image_list())
        elif _b命令 == 'tunnel':
            if _b尾参 and _b尾参[0] == 'start':
                print(f_tunnel_start())
            else:
                print(f_tunnel_ls())
        else:
            return f_未知(_b剩余)
    except BrokenPipeError:
        pass
    except Exception as _b异常:  # noqa: BLE001 —— mock 兜底，任何异常转 JSON error
        print(json.dumps({'error': f'mock error: {_b异常}'}))
        return 1
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(f_main(sys.argv[1:]))
