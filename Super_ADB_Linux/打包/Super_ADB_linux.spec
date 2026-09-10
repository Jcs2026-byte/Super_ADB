# -*- mode: python ; coding: utf-8 -*-
"""
Super_ADB Linux 打包配置
========================
使用相对路径，基于本 spec 文件所在目录（打包/）的上一级（项目根）。
生成 onedir 模式的可执行文件（dist/Super_ADB/Super_ADB）。

用法：
    cd 项目根目录
    pyinstaller 打包/Super_ADB_linux.spec

或使用一键脚本：
    bash 打包/build_linux.sh
"""

import os
import sys

# 项目根目录 = spec 文件所在目录的上一级
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_PROJECT_ROOT = os.path.dirname(_SPEC_DIR)

# 入口脚本
_ENTRY = os.path.join(_PROJECT_ROOT, '项目启动入口', 'Super_ADB_主入口.py')

# 资源目录
_RES_DIR = os.path.join(_PROJECT_ROOT, '资源')
_EXT_DIR = os.path.join(_PROJECT_ROOT, '外部扩展')

# 图标：Linux 用 .png
_ICON = os.path.join(_PROJECT_ROOT, '资源', 'Super_ADB.png')

# datas：资源 + 外部扩展（目标必须相对路径；PyInstaller >=6.22 对前导 / 直接报错）
_datas = [
    (_RES_DIR, '资源'),
]
if os.path.isdir(_EXT_DIR):
    _datas.append((_EXT_DIR, '外部扩展'))

a = Analysis(
    [_ENTRY],
    pathex=[_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, '项目UI')],
    binaries=[],
    datas=_datas,
    hiddenimports=['segno', 'segno.helpers', 'zeroconf', 'ifaddr', 'pyzbar', '工具.android调试工具.收藏下拉框',
              'png_rc', '项目UI.png_rc',
              'cryptography', 'cryptography.hazmat',
              'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.asymmetric',
              'cryptography.hazmat.primitives.asymmetric.rsa',
              'cryptography.hazmat.primitives.asymmetric.padding',
              'cryptography.hazmat.primitives.serialization',
              'cryptography.hazmat.primitives.hashes', 'cryptography.hazmat.backends',
              '工具.android调试工具.ADB工具', '工具.android调试工具.AXML解码器', '工具.便捷工具.JSON读写', '工具.便捷工具.PCAP解析器', '工具.android调试工具.图表JS',
              '工具.便捷工具.轻量PCAP解析', '工具.android调试工具.自研adb.adb协议',
              '对话框.WiFi配对对话框', '对话框.二维码连接页', '对话框.局域网扫描对话框',
              '对话框.设备信息对话框', '对话框.哈希校验对话框', '对话框.环境配置对话框',
              '对话框.JSON工具对话框', '对话框.scrcpy_设置对话框',
              '监控.设备性能监控', '页面.小猫', '页面.文件管理页', '页面.日志查看器页面',
              '项目UI.对话框基类',
              '工具.android调试工具.自研adb.mdns发现', 'usb', 'usb.core', 'usb.util', 'usb.backend.libusb1'],
    hookspath=[os.path.join(_SPEC_DIR, 'hooks')],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(_SPEC_DIR, 'hooks', 'runtime_pkg_alias.py'),
        os.path.join(_SPEC_DIR, 'hooks', 'runtime_pyzbar.py'),
    ],
    excludes=['numpy', 'cv2', 'pyzbar.tests', 'PIL._avif', 'PIL._webp',
              'PIL._imagingtk', 'zstandard', '_zstd', '_decimal',
              'PIL._imagingcms', 'PIL._imagingmath'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Super_ADB',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[_ICON],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Super_ADB',
)
