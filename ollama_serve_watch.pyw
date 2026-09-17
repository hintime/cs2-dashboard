#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自愈守护的 .pyw 入口（无窗口，可被 explorer 双击/命令行启动）

因为 explorer.exe 不能给目标传参数，所以单独做一个入口来跑 `--watch` 模式。
双击本文件（或 `explorer.exe ollama_serve_watch.pyw`）即可启动常驻自愈。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ollama_serve  # noqa: E402

sys.argv = [sys.argv[0], '--watch']
raise SystemExit(ollama_serve.main())
