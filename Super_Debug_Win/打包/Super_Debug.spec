# -*- mode: python ; coding: utf-8 -*-

import os

# 打包目录 = 本 spec 所在目录；项目根 = 打包目录的上一级
# （2026-09 适配 CI：原先硬编码本机绝对路径，
#  在 GitHub Actions runner 上不存在，Windows 构建必挂）
# 注：PyInstaller ≥6.21 执行 spec 时不再注入 __file__（NameError），
#  必须使用 PyInstaller 提供的 SPEC（spec 绝对路径）变量，与 Linux/macOS spec 一致。
_打包目录 = os.path.dirname(os.path.abspath(SPEC))
_项目根 = os.path.dirname(_打包目录)



a = Analysis(
    [os.path.join(_项目根, '项目启动入口', 'Super_Debug_主入口.py')],
    pathex=[_项目根, os.path.join(_项目根, '项目UI')],
    binaries=[],
    datas=[(os.path.join(_项目根, '资源'), '资源'), (os.path.join(_项目根, '外部扩展'), '外部扩展')],
    hiddenimports=['segno', 'segno.helpers', 'zeroconf', 'ifaddr', 'pyzbar', '工具.收藏下拉框', 'png_rc', '项目UI.png_rc', 'cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.asymmetric', 'cryptography.hazmat.primitives.asymmetric.rsa', 'cryptography.hazmat.primitives.asymmetric.padding', 'cryptography.hazmat.primitives.serialization', 'cryptography.hazmat.primitives.hashes', 'cryptography.hazmat.backends', '工具.自研adb.mdns发现', 'usb', 'usb.core', 'usb.util', 'usb.backend.libusb1', 'brotli'],
    hookspath=[os.path.join(_打包目录, 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(_打包目录, 'hooks', 'runtime_pyzbar.py')],
    excludes=['numpy', 'cv2', 'pyzbar.tests', 'PIL._avif', 'PIL._webp', 'PIL._imagingtk', 'zstandard', '_zstd', '_decimal', 'PIL._imagingcms', 'PIL._imagingmath'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Super_Debug',
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
    icon=[os.path.join(_项目根, '资源', 'Super_Debug.png')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Super_Debug',
)
