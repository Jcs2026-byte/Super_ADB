#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke 前校验：解压 zip 后全量检查符号链接断链，失败退出 1。

用法：python3 verify_zip_symlinks.py <xxx.zip>
"""
import os
import shutil
import subprocess
import sys
import tempfile

zip_path = sys.argv[1]
tmp = tempfile.mkdtemp(prefix='verify_symlinks_')
try:
    subprocess.run(['unzip', '-q', zip_path, '-d', tmp], check=True)
    apps = [n for n in os.listdir(tmp) if n.endswith('.app')]
    app = os.path.join(tmp, apps[0]) if apps else tmp
    broken = []
    for dp, dn, fn in os.walk(app):
        for n in dn + fn:
            p = os.path.join(dp, n)
            if os.path.islink(p) and not os.path.exists(p):
                broken.append(os.path.relpath(p, app))
    print('verify broken symlinks:', len(broken))
    for b in broken[:15]:
        print('   ', b)
    if broken:
        sys.exit(1)
    print('OK: no broken symlinks')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
