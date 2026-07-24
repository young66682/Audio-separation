#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
器乐分离程序 v2.4 —— 向后兼容入口

本文件保留用于兼容旧启动方式 (streamlit run mainService.py)。
实际逻辑已迁移到 audio_separator/ 包中，新项目请使用 app.py。
"""

# 直接委托给新入口
from app import main

if __name__ == "__main__":
    main()
