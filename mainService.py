#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
器乐分离程序 v2.3 - Streamlit 简化版
进度和日志输出到控制台，界面只显示结果
"""

import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
import time

try:
    import streamlit as st

    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False
    print("警告: streamlit 未安装，请执行 'pip install streamlit'")

try:
    from demucs.separate import main as demucs_separate

    HAS_DEMUCS = True
except ImportError as e:
    print(f"警告: demucs 导入失败，具体错误: {e}")
    HAS_DEMUCS = False

try:
    from pydub import AudioSegment

    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False
    print("警告:pydub 未安装，请执行 'pip install pydub'")

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

SUPPORTED_STEMS = {
    "vocals": "🎤 人声 (Vocals)",
    "drums": "🥁 鼓 (Drums)",
    "bass": " 贝斯 (Bass)",
    "guitar": "🎸 吉他 (Guitar)",
    "piano": "🎹 钢琴 (Piano)",
    "other": "🎵 其他乐器 (Other)"
}

DEMUCS_4STEMS = ["vocals", "drums", "bass", "other"]
DEMUCS_6STEMS = ["vocals", "drums", "bass", "guitar", "piano", "other"]

MODEL_CONFIGS = {
    "htdemucs": {
        "name": "HTDemucs (默认, 高质量)",
        "stems": DEMUCS_4STEMS,
        "description": "Hybrid Transformer Demucs v4 - 最新架构，仅支持 4 轨：人声/鼓/贝斯/其他",
        "icon": "⚡",
        "supports_guitar": False
    },
    "htdemucs_6s": {
        "name": "HTDemucs 6-Stem (实验性)",
        "stems": DEMUCS_6STEMS,
        "description": "六轨分离模型，支持吉他和钢琴（实验性）",
        "icon": "🔬",
        "supports_guitar": True
    },
    "mdx_q": {
        "name": "MDX (快速模式)",
        "stems": DEMUCS_4STEMS,
        "description": "MDX量化模型，速度较快但质量稍低，仅支持 4 轨",
        "icon": "🚀",
        "supports_guitar": False
    }
}



class MP3Exporter:
    """MP3格式导出器"""

    def __init__(self, output_dir: str, bitrate: int = 192):
        self.output_dir = Path(output_dir)
        self.bitrate = bitrate
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def convert_to_mp3(self, wav_path: Path, stem_name: str) -> Path:
        """将WAV文件转换为MP3"""
        mp3_path = self.output_dir / f"{stem_name}.mp3"

        if not HAS_PYDUB:
            self._convert_via_ffmpeg(wav_path, mp3_path)
        else:
            audio = AudioSegment.from_wav(str(wav_path))
            audio.export(str(mp3_path), format="mp3", bitrate=f"{self.bitrate}k")

        return mp3_path

    def _convert_via_ffmpeg(self, wav_path: Path, mp3_path: Path):
        """使用ffmpeg命令行转换"""
        cmd = [
            "ffmpeg", "-i", str(wav_path),
            "-acodec", "mp3", "-ab", f"{self.bitrate}k",
            "-y", str(mp3_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)


class StemSeparator:
    """核心分离引擎"""

    def __init__(self, model_name: str = "htdemucs", device: str = None):
        if not HAS_DEMUCS:
            raise RuntimeError("demucs未安装，请执行: pip install demucs")

        self.model_name = model_name
        self.device = device or self._detect_device()
        self.separator = None
        self._init_separator()

    def _detect_device(self) -> str:
        """自动检测GPU"""
        import torch
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _init_separator(self):
        """初始化demucs分离器"""
        try:
            self.separator = "cli"
            print(f"✅ 分离器已初始化 - 模型: {self.model_name}, 设备: {self.device}")
        except Exception as e:
            print(f"警告: 初始化失败: {e}")
            self.separator = None

    def separate(self, input_file: Path, selected_stems: List[str],
                 output_dir: Path, progress_callback=None) -> Dict[str, Path]:
        results = {}

        if not input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_file}")

        temp_dir = Path(tempfile.mkdtemp(prefix="demucs_temp_"))

        try:
            if progress_callback:
                progress_callback("加载音频文件...", 0)

            stems = self._separate_cli(input_file, temp_dir, progress_callback)

            if progress_callback:
                progress_callback("导出MP3文件...", 80)

            exporter = MP3Exporter(str(output_dir), bitrate=192)

            for stem in selected_stems:
                if stem not in stems:
                    continue

                wav_path = stems[stem]
                mp3_path = exporter.convert_to_mp3(wav_path, stem)
                results[stem] = mp3_path
                print(f"✅ {stem} -> {mp3_path}")

            if progress_callback:
                progress_callback("分离完成!", 100)

            return results

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _separate_cli(self, input_file: Path, output_dir: Path, progress_callback=None) -> Dict[str, Path]:
        demucs_output = output_dir / self.model_name

        cmd = [
            "python", "-m", "demucs",
            "--out", str(output_dir),
            "--name", self.model_name,
            "--device", self.device,
            str(input_file)
        ]

        if progress_callback:
            progress_callback("运行demucs分离...", 20)

        print(f"\n🎵 开始分离: {input_file.name}")
        print(f"📋 命令: {' '.join(cmd)}\n")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )

        full_output = []
        for line in process.stdout:
            line = line.strip()
            full_output.append(line)
            print(f"  {line}")

        process.wait()

        if process.returncode != 0:
            error_msg = "\n".join(full_output[-10:])
            raise RuntimeError(f"demucs分离过程失败\n错误详情:\n{error_msg}")

        stems_result = {}
        input_basename = input_file.stem

        for stem_name in SUPPORTED_STEMS.keys():
            stem_path = demucs_output / input_basename / f"{stem_name}.wav"
            if stem_path.exists():
                stems_result[stem_name] = stem_path

        return stems_result


def initialize_session_state():
    """初始化会话状态"""
    if 'output_dir' not in st.session_state:
        st.session_state.output_dir = Path.cwd() / "output"
    if 'results' not in st.session_state:
        st.session_state.results = {}
    if 'task_status' not in st.session_state:
        st.session_state.task_status = "idle"
    if 'progress' not in st.session_state:
        st.session_state.progress = 0
    if 'progress_message' not in st.session_state:
        st.session_state.progress_message = "准备中..."


def setup_page_config():
    """设置页面配置"""
    st.set_page_config(
        page_title="🎵 AI 器乐分离工具",
        page_icon="🎵",
        layout="wide",
        initial_sidebar_state="expanded"
    )

# 在文件开头尝试导入 pyperclip（可选依赖）
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False
    print("提示: 安装 pyperclip 可使用粘贴路径功能 (pip install pyperclip)")
import subprocess
import sys

def select_folder_via_subprocess():
    """通过子进程打开文件夹选择对话框，返回路径字符串，若取消则返回 None"""
    script = '''
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
folder = filedialog.askdirectory()
if folder:
    print(folder)
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            return None
    except Exception as e:
        st.error(f"打开文件夹对话框失败: {e}")
        return None


def render_sidebar():
    """渲染侧边栏（支持浏览文件夹、粘贴路径、手动输入）"""
    with st.sidebar:
        st.header("️ 设置")

        st.subheader("📁 输出目录")

        # 输出目录输入框（实时同步）
        def on_output_dir_text_change():
            new_path = st.session_state.output_dir_text
            if new_path:
                p = Path(new_path)
                if p != st.session_state.output_dir:
                    st.session_state.output_dir = p
                    p.mkdir(parents=True, exist_ok=True)

        # 使用 key 方式确保 value 正确同步
        st.text_input(
            "输出目录路径",
            key="output_dir_text",
            on_change=on_output_dir_text_change,
            help="可直接输入或粘贴路径（Ctrl+V）"
        )

        # 显示当前输出目录
        st.caption(f" 当前: `{st.session_state.output_dir}`")

        # 两个辅助按钮：粘贴路径 + 浏览文件夹（子进程方式）
        col1, col2 = st.columns(2)
        with col1:
            if st.button(" 粘贴路径", use_container_width=True):
                if HAS_PYPERCLIP:
                    try:
                        clipboard_text = pyperclip.paste().strip()
                        if clipboard_text:
                            p = Path(clipboard_text)
                            if p.is_dir() or (p.parent.exists() and not p.exists()):
                                st.session_state.output_dir = p
                                st.rerun()
                            else:
                                st.warning("剪贴板内容不是有效的目录路径")
                        else:
                            st.info("剪贴板为空")
                    except Exception as e:
                        st.error(f"读取剪贴板失败: {e}")
                else:
                    st.info("未安装 pyperclip，可使用快捷键 Ctrl+V 粘贴路径")

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


def display_progress_ui():
    """显示进度条UI"""
    if st.session_state.task_status == "processing":
        st.markdown("### 🔄 处理进度")
        progress_bar = st.progress(st.session_state.progress)
        status_text = st.empty()
        status_text.text(f"{st.session_state.progress_message} ({st.session_state.progress}%)")
        return progress_bar, status_text
    return None, None


def render_main_interface():
    """渲染主界面"""
    st.title("🎵 AI 器乐分离工具")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📂 上传音频文件")
        uploaded_files = st.file_uploader(
            "选择音频文件",
            type=['mp3', 'wav', 'flac', 'm4a', 'ogg'],
            accept_multiple_files=True,
            help="支持批量上传多个音频文件",
            disabled=st.session_state.task_status == "processing"
        )

        if uploaded_files:
            st.success(f"✅ 已选择 {len(uploaded_files)} 个文件")
            for idx, file in enumerate(uploaded_files):
                size_mb = file.size / 1024 / 1024
                st.caption(f"{idx + 1}. {file.name} ({size_mb:.2f} MB)")

    with col2:
        st.subheader("🎛️ 模型选择")
        model_options = {key: f"{config['icon']} {config['name']}" for key, config in MODEL_CONFIGS.items()}
        selected_model_key = st.radio(
            "选择AI模型",
            options=list(model_options.keys()),
            format_func=lambda x: model_options[x],
            index=0,
            disabled=st.session_state.task_status == "processing"
        )

        selected_model_config = MODEL_CONFIGS[selected_model_key]
        st.info(f"**{selected_model_config['name']}**\n\n{selected_model_config['description']}")

    st.markdown("---")

    st.subheader("🎸 选择要分离的音轨")

    default_stems = DEMUCS_4STEMS if selected_model_key in ["htdemucs", "mdx_q"] else DEMUCS_6STEMS
    supports_guitar = MODEL_CONFIGS[selected_model_key].get("supports_guitar", False)

    if not supports_guitar:
        st.warning("⚠️ 当前模型不支持吉他/钢琴分离，请选择 'HTDemucs 6-Stem' 模型")

    cols = st.columns(3)
    selected_stems = []

    for idx, (stem_key, stem_name) in enumerate(SUPPORTED_STEMS.items()):
        col_idx = idx % 3
        with cols[col_idx]:
            is_default = stem_key in default_stems

            if not supports_guitar and stem_key in ["guitar", "piano"]:
                st.checkbox(stem_name, value=False, disabled=True, help="当前模型不支持此音轨")
            else:
                if st.checkbox(stem_name, value=is_default, disabled=st.session_state.task_status == "processing"):
                    selected_stems.append(stem_key)

    col_select_all, col_deselect_all = st.columns(2)
    with col_select_all:
        if st.button("✅ 全选", use_container_width=True, disabled=st.session_state.task_status == "processing"):
            for stem_key in SUPPORTED_STEMS.keys():
                if supports_guitar or stem_key not in ["guitar", "piano"]:
                    st.session_state[f"stem_{stem_key}"] = True
            st.rerun()

    with col_deselect_all:
        if st.button(" 取消全选", use_container_width=True, disabled=st.session_state.task_status == "processing"):
            for stem_key in SUPPORTED_STEMS.keys():
                st.session_state[f"stem_{stem_key}"] = False
            st.rerun()

    st.markdown("---")

    if selected_stems:
        st.success(f"✅ 已选择 {len(selected_stems)} 个音轨: {', '.join([SUPPORTED_STEMS[s] for s in selected_stems])}")
    else:
        st.warning("⚠️ 请至少选择一个音轨")

    return uploaded_files, selected_model_key, selected_stems


def process_audio_files(uploaded_files, model_name, selected_stems, progress_bar=None, status_text=None):
    """处理音频文件分离（支持进度更新）"""
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
    all_results = {}

    for idx, uploaded_file in enumerate(uploaded_files):
        file_num = idx + 1
        file_path = Path(uploaded_file.name)
        file_stem = file_path.stem

        print(f"\n{'=' * 60}")
        print(f"📌 处理文件 ({file_num}/{total_files}): {uploaded_file.name}")
        print(f"{'=' * 60}")

        # 更新文件级进度
        file_progress_start = int((idx / total_files) * 100)
        file_progress_end = int(((idx + 1) / total_files) * 100)
        
        st.session_state.progress = file_progress_start
        st.session_state.progress_message = f"处理文件 {file_num}/{total_files}: {uploaded_file.name}"
        if progress_bar:
            progress_bar.progress(file_progress_start)
        if status_text:
            status_text.text(f"{st.session_state.progress_message} ({st.session_state.progress}%)")

        temp_input = Path(tempfile.mkdtemp()) / uploaded_file.name
        with open(temp_input, 'wb') as f:
            f.write(uploaded_file.getbuffer())

        file_output_dir = st.session_state.output_dir / file_stem
        file_output_dir.mkdir(parents=True, exist_ok=True)

        # 创建进度回调函数
        def progress_callback(msg, pct):
            # 计算整体进度 (文件进度 + 文件内进度)
            file_range = file_progress_end - file_progress_start
            overall_progress = file_progress_start + int((pct / 100) * file_range)
            
            st.session_state.progress = overall_progress
            st.session_state.progress_message = f"{uploaded_file.name}: {msg}"
            
            print(f"📊 进度: {overall_progress}% - {msg}")
            
            if progress_bar:
                progress_bar.progress(overall_progress)
            if status_text:
                status_text.text(f"{st.session_state.progress_message} ({overall_progress}%)")

        try:
            print(f"🔧 初始化分离器 - 模型: {model_name}")
            separator = StemSeparator(model_name=model_name)
            print(f"✅ 设备: {separator.device}")

            results = separator.separate(
                temp_input, selected_stems, file_output_dir,
                progress_callback=progress_callback
            )

            file_results = {}
            for stem, path in results.items():
                file_results[stem] = str(path)

            all_results[uploaded_file.name] = {
                'path': str(file_output_dir),
                'stems': file_results
            }

            print(f"\n✅ {uploaded_file.name} 分离完成: {len(results)}/{len(selected_stems)} 音轨")

        except Exception as e:
            print(f"\n❌ {uploaded_file.name} 分离失败: {str(e)}")
            import traceback
            print(traceback.format_exc())
            st.session_state.progress_message = f"❌ {uploaded_file.name} 分离失败: {str(e)}"

        finally:
            shutil.rmtree(temp_input.parent, ignore_errors=True)

    # 完成
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


def display_results(results):
    """显示分离结果并提供下载"""
    if not results:
        return

    st.markdown("---")
    st.subheader("📥 下载分离结果")

    for filename, file_data in results.items():
        with st.expander(f"🎵 {filename}", expanded=True):
            stems_path = file_data.get('stems', {})

            for stem_key, stem_path_str in stems_path.items():
                stem_path = Path(stem_path_str)
                if stem_path.exists():
                    col1, col2, col3 = st.columns([2, 1, 1])

                    with col1:
                        st.markdown(f"**{SUPPORTED_STEMS[stem_key]}**")

                    with col2:
                        size_mb = stem_path.stat().st_size / 1024 / 1024
                        st.caption(f"{size_mb:.2f} MB")

                    with col3:
                        try:
                            with open(stem_path, 'rb') as f:
                                st.download_button(
                                    label="⬇️ 下载",
                                    data=f.read(),
                                    file_name=stem_path.name,
                                    mime="audio/mpeg",
                                    key=f"download_{filename}_{stem_key}"
                                )
                        except Exception as e:
                            st.error(f"下载失败: {e}")


def main():
    """主函数入口"""
    setup_page_config()
    initialize_session_state()
    render_sidebar()

    if not HAS_DEMUCS:
        st.error("❌ Demucs 未安装")
        st.code("pip install demucs")
        return

    if not HAS_PYDUB:
        st.warning("⚠️ PyDub 未安装，MP3导出将使用ffmpeg命令行")
        st.code("pip install pydub")

    uploaded_files, model_name, selected_stems = render_main_interface()

    # 显示进度条UI（如果在处理中）
    progress_bar, status_text = display_progress_ui()

    if st.session_state.task_status == "processing":
        # 显示进度中，不需要sleep，让UI更新
        pass

    start_button = st.button(
        "▶ 开始分离",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.task_status == "processing" or not uploaded_files or not selected_stems
    )

    if start_button:
        st.session_state.task_status = "processing"
        st.session_state.progress = 0
        st.session_state.progress_message = "准备开始..."
        st.rerun()

    # 第二次运行：实际处理
    if st.session_state.task_status == "processing" and progress_bar is not None:
        results = process_audio_files(uploaded_files, model_name, selected_stems, progress_bar, status_text)
        if results:
            st.session_state.results = results
        st.session_state.task_status = "completed"
        st.rerun()

    if st.session_state.results:
        display_results(st.session_state.results)

        if st.button(" 开始新的分离", use_container_width=True):
            st.session_state.results = {}
            st.session_state.task_status = "idle"
            st.session_state.progress = 0
            st.session_state.progress_message = "准备中..."
            st.rerun()


if __name__ == "__main__":
    main()
