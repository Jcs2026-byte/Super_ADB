#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 .app 内两类断链符号链接（PyInstaller 6.21/6.22 + PySide6 6.11.2 + Python 3.14 打包产物）：
1) Contents/Resources/Qt*、Contents/Resources/Python 兼容符号链接，目标以 PySide6/ 或
   Python.framework 开头但缺 ../Frameworks/ 前缀（PySide6 框架本体在 Contents/Frameworks/ 下）。
   —— 无条件重建：无论目标当前是否解析，一律指向 ../Frameworks/<target>。
2) Contents/Frameworks/PySide6/Qt/lib/*.framework/Versions/Current 缺失（framework 标准结构）。
用法：python3 fix_symlinks.py <Super_ADB_MAC.app>
"""
import os
import sys

APP = sys.argv[1]
fixed = 0
broken_after = []

# 1) Resources 兼容链接（无条件重建）
RES = os.path.join(APP, 'Contents', 'Resources')
if os.path.isdir(RES):
    for name in sorted(os.listdir(RES)):
        p = os.path.join(RES, name)
        if not os.path.islink(p):
            continue
        target = os.readlink(p)
        if not (target.startswith('PySide6/') or target.startswith('Python.framework')):
            continue
        if target.startswith('../'):
            continue  # 已是修复形态
        new_target = os.path.join('..', 'Frameworks', target)
        os.unlink(p)
        os.symlink(new_target, p)
        fixed += 1
        print('[fix] Resources/%s -> %s (was %s)' % (name, new_target, target))

# 2) Frameworks 内 Qt framework 的 Versions/Current
FW = os.path.join(APP, 'Contents', 'Frameworks', 'PySide6', 'Qt', 'lib')
if os.path.isdir(FW):
    for name in sorted(os.listdir(FW)):
        if not name.endswith('.framework'):
            continue
        fwdir = os.path.join(FW, name)
        versions = os.path.join(fwdir, 'Versions')
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

# 3) 复查剩余断链
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
