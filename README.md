# Fretline：器乐分离、指定乐器伴奏与吉他扒谱

Fretline 是一个本地优先的 Web 工作台，把音频分离、去轨伴奏和吉他扒谱放在同一套
FastAPI + Vue 应用中。

## 已实现功能

- 使用 Demucs 在本地分离整首歌曲，默认支持 4 轨和 6 轨模型。
- 输出人声、鼓组、贝斯、吉他、钢琴、其他乐器等独立音轨。
- 勾选任意乐器后，自动混合其余音轨，生成“去掉该乐器”的伴奏。
- 多个乐器可同时勾选，每个乐器会生成一份独立伴奏。
- 全部音轨、伴奏、清单和原始歌曲可打包为 ZIP。
- 上传歌曲后可按文件名联网查询市面已有的 Backing Track、Karaoke、
  Instrumental 和指定乐器去轨版本，并直接试听或跳转查看。
- 曲谱速查优先返回弹琴吧（tan8.com）的具体中文吉他谱页面，并提供
  Songsterr、MuseScore 和 Ultimate Guitar 的备用搜索入口。
- 实时显示任务阶段和 Demucs 分离进度。
- 单吉他音频可生成六线谱、MIDI、MusicXML 和音符 JSON。
- 可选 MVSEP 云端双吉他路线，将歌曲拆成主音与节奏吉他后分别扒谱。
- CPU、CUDA 和 Apple MPS 自动选择，4 轨 / 6 轨模型按内存与质量需求切换。

## 一键安装与启动

环境要求：

- Python 3.11
- Node.js 20+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg 与 ffprobe，并加入 `PATH`

Windows PowerShell：

```powershell
cd "G:\python\poject\Audio separation"
.\setup.ps1
.\start.ps1
```

安装脚本默认使用清华 PyPI 镜像；其他网络环境可指定官方源：

```powershell
.\setup.ps1 -IndexUrl https://pypi.org/simple
```

打开 <http://127.0.0.1:8000>。首次分离某个模型时，Demucs 会自动下载模型权重。
之后权重会被缓存，可以离线分离。

修改前端后重新构建并启动：

```powershell
.\start.ps1 -RebuildFrontend
```

需要开发热重载：

```powershell
.\start.ps1 -Reload
```

## 使用方式

### 分离与伴奏

1. 选择“分离与伴奏”。
2. 上传歌曲并选择分离模型与处理质量。
3. 勾选要去掉的乐器。
4. 开始处理。
5. 在结果页试听或下载独立音轨、指定伴奏和完整 ZIP。

“去掉吉他”的处理方式是：识别人声、鼓、贝斯、钢琴和其他乐器等剩余音轨，
再把它们混合成伴奏。AI 分离不是数学上的完美反相消除，失真吉他、混响和声像重叠
仍可能留下少量串音。

市面伴奏速查默认使用文件名作为歌曲名，并调用 Apple Music/iTunes Search 接口。
文件名不准确时可以在速查面板里修改歌曲名和艺人后重新查询。该功能只返回官方
商品和试听链接，不下载第三方版权音频；没有找到时会提示直接使用本地分离。

切换到“曲谱”标签会按相同歌曲名和艺人优先查询弹琴吧的中文吉他谱。国内接口
不可用时会回退到 Ultimate Guitar；打开第三方曲谱仍需遵守对应网站的访问和版权
规则。

### 吉他扒谱

- “单吉他音轨”完全在本地识别，适合已经分离好的 guitar stem 或独奏。
- “整曲双吉他”使用 MVSEP 云端分离，需要 Token；音频会上传到 MVSEP。
- 两种模式均支持自动测速、调弦、变调夹、品位范围、和弦跨度和力度门槛。
- 导出格式包括文本六线谱、MIDI、MusicXML 和原始音符事件 JSON。

## 模型与性能

| 模型 | 音轨 | 适用场景 |
| --- | --- | --- |
| `htdemucs` | 人声、鼓、贝斯、其他 | 默认，速度和内存最均衡 |
| `htdemucs_6s` | 人声、鼓、贝斯、吉他、钢琴、其他 | 指定吉他/钢琴伴奏，速度较慢 |
| `mdx_extra_q` | 人声、鼓、贝斯、其他 | 质量优先，CPU 上较慢 |

“快速 / 均衡 / 高质量”分别控制 Demucs shifts 与 overlap。CPU 上推荐先用
`htdemucs` + 快速模式验证流程，再用 6 轨模型精细分离。

### NVIDIA GPU 加速

后端依赖默认锁定为 PyTorch/TorchAudio `2.9.1 + CUDA 13.0`。当前机器的
RTX 4060 Laptop 会自动使用 `cuda`，不需要另外安装完整 CUDA Toolkit，只需安装
兼容的 NVIDIA 驱动。首次运行 `setup.ps1` 需要下载约 1.8 GB 的 GPU 运行时。

检查当前设备和 CUDA 是否可用：

```powershell
.\backend\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

页面右上角会显示“本地分离引擎就绪 / CUDA”。如果驱动或显卡不可用，应用会回退到
CPU，避免直接中断任务。

可通过 `backend/.env` 强制设备：

```dotenv
DEMUCS_DEVICE=cpu
DEMUCS_JOB_TIMEOUT_SECONDS=7200
```

## 云端双吉他配置（可选）

复制配置并填写 MVSEP Token：

```powershell
Copy-Item backend\.env.example backend\.env
```

```dotenv
MVSEP_API_TOKEN=your_token
MVSEP_WORKFLOW=guitar_first
```

修改 `.env` 后重启后端。Token 只保存在后端，不会发送给浏览器。没有 Token 时，
本地分离和单吉他扒谱仍可正常使用。

## 手动开发

后端：

```powershell
cd backend
uv sync --extra dev
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端：

```powershell
cd frontend
npm ci
npm run dev
```

前端开发服务器为 <http://127.0.0.1:5173>，`/api` 会代理到 8000 端口。

## 测试

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm run build
```

测试覆盖本地分离任务、模型音轨校验、伴奏混音、ZIP/下载 API、双吉他流水线和
MusicXML/MIDI 导出。

## 数据与输出

- 后端任务目录：`backend/data/jobs/`
- 分离音轨：`backend/data/jobs/separations/<job-id>/stems/`
- 指定伴奏：`backend/data/jobs/separations/<job-id>/accompaniments/`
- 分离清单：`backend/data/jobs/separations/<job-id>/manifest.json`
- 构建后的前端：`frontend/dist/`

任务状态保存在当前进程内；重启后端后，旧任务不会继续出现在任务列表中。结果文件
仍保留在磁盘中，可在确认不再需要后人工清理。

## API

- `GET /api/health`：运行时、设备、模型和转录能力。
- `POST /api/market/search`：按歌曲名查询市面伴奏和试听链接。
- `POST /api/scores/search`：查询弹琴吧现有曲谱，并提供国际谱库备用入口。
- `POST /api/separations`：上传音频并创建本地分离任务。
- `GET /api/separations/{job_id}`：查询任务与结果。
- `GET /api/separations/{job_id}/events`：SSE 实时进度。
- `GET /api/separations/{job_id}/audio/source`：原曲。
- `GET /api/separations/{job_id}/audio/{stem|accompaniment}/{key}`：音轨或伴奏。
- `GET /api/separations/{job_id}/archive`：完整 ZIP。
- `POST /api/transcriptions`：单吉他扒谱。
- `POST /api/song-transcriptions`：云端双吉他扒谱。

完整交互式接口文档位于 <http://127.0.0.1:8000/docs>。

## 许可与致谢

项目代码见仓库许可证。核心模型与工具包括
[Demucs](https://github.com/facebookresearch/demucs)、
[Basic Pitch](https://github.com/spotify/basic-pitch)、
[alphaTab](https://www.alphatab.net/) 和 [FFmpeg](https://ffmpeg.org/)。
