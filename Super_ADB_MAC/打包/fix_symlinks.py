#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 .app 内全部已知断链符号链接（PyInstaller 6.21 + PySide6 6.11.2 + Python 3.14 打包产物）：
1) Contents/Resources/Qt*、Contents/Resources/Python 兼容链接：缺 ../Frameworks/ 前缀
   （PySide6 框架本体在 Contents/Frameworks/PySide6/Qt/lib 下）→ ../Frameworks/<target>。
2) Contents/Resources/libshiboken6*.dylib -> shiboken6/... ：缺 ../Frameworks/ 前缀 → ../Frameworks/shiboken6/...。
3) Contents/Resources|Frameworks/lib*.dylib -> PIL/.dylibs/... ：PyInstaller 把 Pillow 的
   .dylibs 目录转义为 __dot__dylibs，兼容链接未转义 → 指向 PIL/__dot__dylibs/...。
4) Contents/Resources/外部扩展/scrcpy/scrcpy-macos-aarch64-v4.1/{adb,scrcpy} -> ../../../../Frameworks/外部扩展/...v4.1/...
   ：Frameworks 侧目录名被转义为 v4__dot__1 → 改写 target。
5) Contents/Frameworks/PySide6/Qt/lib/*.framework/Versions/Current 缺失 → 创建 symlink A。
用法：python3 fix_symlinks.py <Super_ADB_MAC.app>
"""
import os
import sys

APP = sys.argv[1]
fixed = 0
broken_after = []
RES = os.path.join(APP, 'Contents', 'Resources')
FW = os.path.join(APP, 'Contents', 'Frameworks')


def _relink(p, new_target, why):
    global fixed
    os.unlink(p)
    os.symlink(new_target, p)
    fixed += 1
    print('[fix] %s -> %s (%s)' % (os.path.relpath(p, APP), new_target, why))


# 1) Resources 兼容链接（Qt*/Python/shiboken6 缺 ../Frameworks/ 前缀）——无条件
if os.path.isdir(RES):
    for name in sorted(os.listdir(RES)):
        p = os.path.join(RES, name)
        if not os.path.islink(p):
            continue
        target = os.readlink(p)
        if target.startswith('../'):
            continue
        if target.startswith('PySide6/') or target.startswith('Python.framework') or target.startswith('shiboken6/'):
            _relink(p, os.path.join('..', 'Frameworks', target), 'frameworks-prefix')

# 2) PIL/.dylibs 兼容链接（Resources 与 Frameworks 两层）
for base, prefix in ((RES, os.path.join('..', 'Frameworks')), (FW, '')):
    if not os.path.isdir(base):
        continue
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if not os.path.islink(p):
            continue
        target = os.readlink(p)
        if not target.startswith('PIL/.dylibs/'):
            continue
        real = 'PIL/__dot__dylibs/' + target[len('PIL/.dylibs/'):]
        _relink(p, os.path.join(prefix, real) if prefix else real, 'pil-dot-dylibs')

# 3) Resources/外部扩展/scrcpy v4.1 兼容链接（Frameworks 侧目录名转义 v4__dot__1）
EXT = os.path.join(RES, '外部扩展', 'scrcpy', 'scrcpy-macos-aarch64-v4.1')
if os.path.isdir(EXT):
    for name in ('adb', 'scrcpy'):
        p = os.path.join(EXT, name)
        if os.path.islink(p) and not os.path.exists(p):
            _relink(p, '../../../../Frameworks/外部扩展/scrcpy/scrcpy-macos-aarch64-v4__dot__1/' + name,
                    'v4-dot-1-escape')

# 4) Frameworks 内 Qt framework 的 Versions/Current
QTLIB = os.path.join(FW, 'PySide6', 'Qt', 'lib')
if os.path.isdir(QTLIB):
    for name in sorted(os.listdir(QTLIB)):
        if not name.endswith('.framework'):
            continue
        versions = os.path.join(QTLIB, name, 'Versions')
        if not os.path.isdir(versions):
            continue
        current = os.path.join(versions, 'Current')
        if os.path.islink(current) and os.path.exists(current):
            continue
        a_dir = os.path.join(versions, 'A')
        if os.path.isdir(a_dir):
            if os.path.lexists(current):
                os.unlink(current)
            os.symlink('A', current)
            fixed += 1
            print('[fix] %s/Versions/Current -> A' % name)

# 5) 复查剩余断链
for dirpath, dirs, files in os.walk(APP):
    if os.path.islink(dirpath) and not os.path.exists(dirpath):
        broken_after.append(os.path.relpath(dirpath, APP))
    for fn in files:
        fp = os.path.join(dirpath, fn)
        if os.path.islink(fp) and not os.path.exists(fp):
            broken_after.append(os.path.relpath(fp, APP))

print('[fix] 修复 %d 个符号链接' % fixed)
if broken_after:
    print('[fix][WARN] 仍存在 %d 个断链:' % len(broken_after))
    for b in broken_after[:20]:
        print('    ', b)
else:
    print('[fix] OK: 无剩余断链')
