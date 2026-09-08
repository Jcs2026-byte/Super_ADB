#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 PyInstaller(PySide6 6.11) 在 macOS .app 里生成的「断链兼容符号链接」。

现象（Python 3.14 + PyInstaller 6.21/6.22 + PySide6 6.11.2）：
  PySide6 框架本体落在 Contents/Frameworks/PySide6/，
  但 PyInstaller 在 Contents/Resources/ 生成的兼容符号链接
  (Qt* -> PySide6/Qt/lib/...、Python -> Python.framework/...) 目标缺
  ../Frameworks/ 前缀，全部断链。
  断链后果：Qt 插件/框架加载失败、Resources/Python 断链使解释器 stdlib
  路径解析错误（_struct ModuleNotFoundError, rc=255）。

本脚本把 Resources 下「目标以 PySide6/ 或 Python.framework 开头且不存在」的
符号链接重建为 ../Frameworks/<原名>，恢复可解析。
用法：python3 fix_symlinks.py <Super_ADB_MAC.app>
"""
import os
import sys

APP = sys.argv[1]
RES = os.path.join(APP, 'Contents', 'Resources')
if not os.path.isdir(RES):
    print('[fix_symlinks][ERROR] 不是 .app: %s' % APP)
    sys.exit(1)

fixed = 0
for name in sorted(os.listdir(RES)):
    p = os.path.join(RES, name)
    if not os.path.islink(p):
        continue
    target = os.readlink(p)
    if not (target.startswith('PySide6/') or target.startswith('Python.framework')):
        continue
    full = os.path.join(RES, target)
    if os.path.exists(full):
        continue
    new_target = os.path.join('..', 'Frameworks', target)
    os.unlink(p)
    os.symlink(new_target, p)
    fixed += 1
    print('[fix_symlinks] 修复 %s: %s -> %s' % (name, target, new_target))

print('[fix_symlinks] 完成，共修复 %d 个断链符号链接' % fixed)
