#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 器乐分离工具 v2.4 —— 应用入口
-----------------------------------
基于 Facebook Demucs 的音频音轨分离 Web 应用。

用法:
    streamlit run app.py
"""

import streamlit as st

from audio_separator.config import HAS_DEMUCS, HAS_PYDUB
from audio_separator.ui import (
    setup_page_config,
    initialize_session_state,
    render_sidebar,
    display_progress_ui,
    render_main_interface,
    process_audio_files,
    display_results,
)


# ======================================================================
# 主函数
# ======================================================================


def main() -> None:
    """Streamlit 应用主入口。"""
    setup_page_config()
    initialize_session_state()
    render_sidebar()

    # ---- 依赖检查 ----
    if not HAS_DEMUCS:
        st.error("❌ Demucs 未安装")
        st.code("pip install demucs")
        return

    if not HAS_PYDUB:
        st.warning("⚠️ PyDub 未安装，MP3 导出将使用 ffmpeg 命令行")
        st.code("pip install pydub")

    # ---- 主界面 ----
    uploaded_files, model_name, selected_stems = render_main_interface()
    progress_bar, status_text = display_progress_ui()

    # ---- 开始按钮 ----
    start_disabled = (
        st.session_state.task_status == "processing"
        or not uploaded_files
        or not selected_stems
    )
    if st.button(
        "▶ 开始分离",
        type="primary",
        use_container_width=True,
        disabled=start_disabled,
    ):
        st.session_state.task_status = "processing"
        st.session_state.progress = 0
        st.session_state.progress_message = "准备开始..."
        st.rerun()

    # ---- 实际处理 ----
    if st.session_state.task_status == "processing" and progress_bar is not None:
        results = process_audio_files(
            uploaded_files, model_name, selected_stems, progress_bar, status_text
        )
        if results:
            st.session_state.results = results
        st.session_state.task_status = "completed"
        st.rerun()

    # ---- 结果展示 ----
    if st.session_state.results:
        display_results(st.session_state.results)

        if st.button("🔄 开始新的分离", use_container_width=True):
            st.session_state.results = {}
            st.session_state.task_status = "idle"
            st.session_state.progress = 0
            st.session_state.progress_message = "准备中..."
            st.rerun()


# ======================================================================
# 启动
# ======================================================================

if __name__ == "__main__":
    main()
