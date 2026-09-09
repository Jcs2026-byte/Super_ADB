# -*- coding: utf-8 -*-
"""
工具 / Ios调试模块
==================
go-ios（MIT，Go 静态二进制）桥接层。
只负责「跑命令拿 JSON / 文本」，不做 UI、不做业务语义换算。

命令清单参考 go-ios README（https://github.com/danielpaulus/go-ios）：
    list / version / info / apps / launch / kill / install --path / uninstall
    screenshot --output / crash ls / crash cp / syslog / sysmontap
    batterycheck / diskspace / ps / devmode / image auto / image list
    tunnel ls / tunnel start

命名约定（本模块全部为新建代码）：
    类名    前缀 c   → cIos设备操作
    方法名  前缀 f   → f获取设备列表
    变量名  前缀 b   → b设备列表
"""
