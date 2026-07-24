#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit 界面 —— 所有 UI 渲染函数。
"""

import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

from .config import (
    HAS_DEMUCS,
    HAS_PYDUB,
    HAS_PYPERCLIP,
    SUPPORTED_STEMS,
    DEMUCS_4STEMS,
    DEMUCS_6STEMS,
    MODEL_CONFIGS,
)
from .engine import StemSeparator


# ======================================================================
# 页面初始化
# ======================================================================


def setup_page_config() -> None:
    """配置 Streamlit 页面元信息。"""
    st.set_page_config(
        page_title="🎵 AI 器乐分离工具",
        page_icon="🎵",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def initialize_session_state() -> None:
    """初始化会话状态中的默认值。"""
    defaults = {
        "output_dir": Path.cwd() / "output",
        "results": {},
        "task_status": "idle",
        "progress": 0,
        "progress_message": "准备中...",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ======================================================================
# 工具函数
# ======================================================================


def select_folder_via_subprocess() -> Optional[str]:
    """通过子进程打开 tkinter 文件夹选择对话框。

    Returns:
        选择的文件夹路径，若取消则返回 None。
    """
    script = """
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
folder = filedialog.askdirectory()
if folder:
    print(folder)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception as exc:
        st.error(f"打开文件夹对话框失败: {exc}")
        return None


# ======================================================================
# 侧边栏
# ======================================================================


def render_sidebar() -> None:
    """渲染侧边栏 —— 输出目录设置。"""
    with st.sidebar:
        st.header("⚙️ 设置")
        st.subheader("📁 输出目录")

        def _on_output_dir_change() -> None:
            new_path = st.session_state.output_dir_text
            if new_path:
                p = Path(new_path)
                if p != st.session_state.output_dir:
                    st.session_state.output_dir = p
                    p.mkdir(parents=True, exist_ok=True)

        st.text_input(
            "输出目录路径",
            key="output_dir_text",
            on_change=_on_output_dir_change,
            help="可直接输入或粘贴路径（Ctrl+V）",
        )

        st.caption(f"📌 当前: `{st.session_state.output_dir}`")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📋 粘贴路径", use_container_width=True):
                if HAS_PYPERCLIP:
                    try:
                        import pyperclip

                        text = pyperclip.paste().strip()
                        if text:
                            p = Path(text)
                            if p.is_dir() or (p.parent.exists() and not p.exists()):
                                st.session_state.output_dir = p
                                st.rerun()
                            else:
                                st.warning("剪贴板内容不是有效的目录路径")
                        else:
                            st.info("剪贴板为空")
                    except Exception as exc:
                        st.error(f"读取剪贴板失败: {exc}")
                else:
                    st.info("未安装 pyperclip，可直接使用 Ctrl+V 粘贴路径")

        with col2:
            if st.button("📂 浏览文件夹", use_container_width=True):
                folder = select_folder_via_subprocess()
                if folder:
                    st.session_state.output_dir = Path(folder)
                    st.success(f"✅ 已选择: {folder}")
                    st.rerun()
                else:
                    st.info("未选择文件夹")

        st.divider()


# ======================================================================
# 进度 UI
# ======================================================================


def display_progress_ui():
    """渲染进度条组件。

    Returns:
        (progress_bar, status_text) 或 (None, None)（非处理中状态时）。
    """
    if st.session_state.task_status != "processing":
        return None, None

    st.markdown("### 🔄 处理进度")
    progress_bar = st.progress(st.session_state.progress)
    status_text = st.empty()
    status_text.text(
        f"{st.session_state.progress_message} ({st.session_state.progress}%)"
    )
    return progress_bar, status_text


# ======================================================================
# 主界面
# ======================================================================


def render_main_interface():
    """渲染主界面 —— 文件上传、模型选择、音轨选择。

    Returns:
        (uploaded_files, model_name, selected_stems) 三元组。
    """
    st.title("🎵 AI 器乐分离工具")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    # -- 文件上传 --------------------------------------------------------
    with col1:
        st.subheader("📂 上传音频文件")
        uploaded_files = st.file_uploader(
            "选择音频文件",
            type=["mp3", "wav", "flac", "m4a", "ogg"],
            accept_multiple_files=True,
            help="支持批量上传多个音频文件",
            disabled=st.session_state.task_status == "processing",
        )

        if uploaded_files:
            st.success(f"✅ 已选择 {len(uploaded_files)} 个文件")
            for idx, file in enumerate(uploaded_files):
                size_mb = file.size / 1024 / 1024
                st.caption(f"{idx + 1}. {file.name} ({size_mb:.2f} MB)")

    # -- 模型选择 --------------------------------------------------------
    with col2:
        st.subheader("🎛️ 模型选择")
        model_options = {
            key: f"{cfg['icon']} {cfg['name']}"
            for key, cfg in MODEL_CONFIGS.items()
        }
        selected_model_key = st.radio(
            "选择 AI 模型",
            options=list(model_options.keys()),
            format_func=lambda x: model_options[x],
            index=0,
            disabled=st.session_state.task_status == "processing",
        )

        cfg = MODEL_CONFIGS[selected_model_key]
        st.info(f"**{cfg['name']}**\n\n{cfg['description']}")

    st.markdown("---")

    # -- 音轨选择 --------------------------------------------------------
    st.subheader("🎸 选择要分离的音轨")

    selected_cfg = MODEL_CONFIGS[selected_model_key]
    default_stems = (
        DEMUCS_4STEMS if selected_model_key in ("htdemucs", "mdx_q")
        else DEMUCS_6STEMS
    )
    supports_guitar = selected_cfg.get("supports_guitar", False)

    if not supports_guitar:
        st.warning("⚠️ 当前模型不支持吉他/钢琴分离，请选择 'HTDemucs 6-Stem' 模型")

    cols = st.columns(3)
    selected_stems: List[str] = []

    for idx, (stem_key, stem_name) in enumerate(SUPPORTED_STEMS.items()):
        with cols[idx % 3]:
            is_default = stem_key in default_stems
            disabled = (
                not supports_guitar
                and stem_key in ("guitar", "piano")
                or st.session_state.task_status == "processing"
            )
            checked = st.checkbox(
                stem_name,
                value=is_default and not disabled,
                disabled=disabled,
                key=f"stem_{stem_key}",
            )
            if checked:
                selected_stems.append(stem_key)

    # 全选 / 取消全选
    col_all, col_none = st.columns(2)
    is_processing = st.session_state.task_status == "processing"
    with col_all:
        if st.button("✅ 全选", use_container_width=True, disabled=is_processing):
            for stem_key in SUPPORTED_STEMS:
                if supports_guitar or stem_key not in ("guitar", "piano"):
                    st.session_state[f"stem_{stem_key}"] = True
            st.rerun()
    with col_none:
        if st.button("❌ 取消全选", use_container_width=True, disabled=is_processing):
            for stem_key in SUPPORTED_STEMS:
                st.session_state[f"stem_{stem_key}"] = False
            st.rerun()

    st.markdown("---")

    if selected_stems:
        labels = ", ".join(SUPPORTED_STEMS[s] for s in selected_stems)
        st.success(f"✅ 已选择 {len(selected_stems)} 个音轨: {labels}")
    else:
        st.warning("⚠️ 请至少选择一个音轨")

    return uploaded_files, selected_model_key, selected_stems


# ======================================================================
# 处理逻辑
# ======================================================================


def process_audio_files(
    uploaded_files,
    model_name: str,
    selected_stems: List[str],
    progress_bar=None,
    status_text=None,
) -> Optional[Dict]:
    """批量处理音频文件分离。

    Args:
        uploaded_files:   Streamlit 上传文件列表。
        model_name:       模型 key。
        selected_stems:   用户选择的音轨列表。
        progress_bar:     Streamlit 进度条组件。
        status_text:      Streamlit 状态文本组件。

    Returns:
        {filename: {"path": ..., "stems": {stem: path}}} 或 None。
    """
    if not uploaded_files:
        st.error("❌ 请先上传音频文件")
        return None

    if not selected_stems:
        st.error("❌ 请至少选择一个音轨")
        return None

    print("\n" + "=" * 60)
    print("🚀 开始音频分离任务")
    print("=" * 60)

    total_files = len(uploaded_files)
    all_results: Dict = {}

    for idx, uploaded_file in enumerate(uploaded_files):
        file_num = idx + 1

        print(f"\n{'=' * 60}")
        print(f"📌 处理文件 ({file_num}/{total_files}): {uploaded_file.name}")
        print(f"{'=' * 60}")

        # 计算文件级进度区间
        file_start = int((idx / total_files) * 100)
        file_end = int(((idx + 1) / total_files) * 100)

        st.session_state.progress = file_start
        st.session_state.progress_message = (
            f"处理文件 {file_num}/{total_files}: {uploaded_file.name}"
        )
        if progress_bar:
            progress_bar.progress(file_start)
        if status_text:
            status_text.text(
                f"{st.session_state.progress_message} ({st.session_state.progress}%)"
            )

        # 写入临时文件
        temp_input = Path(tempfile.mkdtemp()) / uploaded_file.name
        with open(temp_input, "wb") as f:
            f.write(uploaded_file.getbuffer())

        file_output_dir = st.session_state.output_dir / Path(uploaded_file.name).stem
        file_output_dir.mkdir(parents=True, exist_ok=True)

        def _progress_callback(msg: str, pct: int) -> None:
            overall = file_start + int((pct / 100) * (file_end - file_start))
            st.session_state.progress = overall
            st.session_state.progress_message = f"{uploaded_file.name}: {msg}"
            print(f"📊 进度: {overall}% - {msg}")
            if progress_bar:
                progress_bar.progress(overall)
            if status_text:
                status_text.text(
                    f"{st.session_state.progress_message} ({overall}%)"
                )

        try:
            print(f"🔧 初始化分离器 —— 模型: {model_name}")
            separator = StemSeparator(model_name=model_name)
            print(f"✅ 设备: {separator.device}")

            results = separator.separate(
                temp_input,
                selected_stems,
                file_output_dir,
                progress_callback=_progress_callback,
            )

            file_results = {stem: str(path) for stem, path in results.items()}
            all_results[uploaded_file.name] = {
                "path": str(file_output_dir),
                "stems": file_results,
            }

            n_ok = len(results)
            print(f"\n✅ {uploaded_file.name} 分离完成: {n_ok}/{len(selected_stems)} 音轨")

        except Exception as exc:
            import traceback

            print(f"\n❌ {uploaded_file.name} 分离失败: {exc}")
            traceback.print_exc()
            st.session_state.progress_message = (
                f"❌ {uploaded_file.name} 分离失败: {exc}"
            )
        finally:
            shutil.rmtree(temp_input.parent, ignore_errors=True)

    # 全部完成
    st.session_state.progress = 100
    st.session_state.progress_message = "所有任务完成！"
    if progress_bar:
        progress_bar.progress(100)
    if status_text:
        status_text.text("所有任务完成！(100%)")

    print("\n" + "=" * 60)
    print("🎉 所有任务处理完成！")
    print("=" * 60 + "\n")

    return all_results


# ======================================================================
# 结果展示
# ======================================================================


def display_results(results: Dict) -> None:
    """展示分离结果并提供单文件下载按钮。

    Args:
        results: 来自 process_audio_files 的结果字典。
    """
    if not results:
        return

    st.markdown("---")
    st.subheader("📥 下载分离结果")

    for filename, file_data in results.items():
        with st.expander(f"🎵 {filename}", expanded=True):
            stems_path = file_data.get("stems", {})

            for stem_key, stem_path_str in stems_path.items():
                stem_path = Path(stem_path_str)
                if not stem_path.exists():
                    continue

                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.markdown(f"**{SUPPORTED_STEMS.get(stem_key, stem_key)}**")
                with col2:
                    size_mb = stem_path.stat().st_size / 1024 / 1024
                    st.caption(f"{size_mb:.2f} MB")
                with col3:
                    try:
                        with open(stem_path, "rb") as f:
                            st.download_button(
                                label="⬇️ 下载",
                                data=f.read(),
                                file_name=stem_path.name,
                                mime="audio/mpeg",
                                key=f"download_{filename}_{stem_key}",
                            )
                    except Exception as exc:
                        st.error(f"下载失败: {exc}")
