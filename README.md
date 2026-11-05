<p align="center">
  <img src="frontend/public/brand-icon.png" width="128" alt="Fretline logo" />
</p>

<h1 align="center">Fretline</h1>

<p align="center">
  本地优先的器乐分离、指定乐器伴奏与吉他扒谱工作台
</p>

Fretline 将 Demucs 本地音轨分离、指定乐器去轨、Basic Pitch 吉他扒谱、
MVSEP 双吉他分离、MusicXML 导出和国内伴奏/曲谱查询整合在一个 FastAPI + Vue
Web 应用中。

## 功能总览

### 本地分离与伴奏

- 使用 Demucs 在本地分离歌曲，音频无需上传到第三方服务。
- 支持 4 轨与 6 轨模型：
  - `htdemucs`：人声、鼓、贝斯、其他乐器。
  - `htdemucs_6s`：人声、鼓、贝斯、吉他、钢琴、其他乐器。
  - `mdx_extra_q`：质量优先的 4 轨分离。
- 勾选任意乐器后，将剩余音轨自动混音成“去掉该乐器”的伴奏。
- 可同时生成多个不同乐器的伴奏文件。
- 支持快速、均衡、高质量三档处理设置。
- 自动选择 NVIDIA CUDA、Apple MPS 或 CPU。
- 实时显示模型加载、分离进度、伴奏混音和打包状态。
- 可试听和下载独立音轨、指定伴奏、原曲与完整 ZIP。
- 上传文件会经过格式、大小、音频流和时长校验，损坏文件不会进入任务队列。

### 单吉他扒谱

- 使用 Basic Pitch 在本地识别复音吉他。
- 自动过滤常见的弱泛音重复音符。
- 支持自动测速或手动指定 BPM。
- 支持十六分音符量化、最短音符时长和力度门槛。
- 根据调弦、变调夹、最高品位、和弦跨度自动分配琴弦与品位。
- 支持标准调弦、Drop D、降半音、Open G、DADGAD 等预设，也可输入自定义调弦。
- 导出格式：
  - 文本六线谱 `TXT`
  - MIDI
  - MusicXML
  - 音符事件 `JSON`

### 整曲双吉他

- 可选使用 MVSEP 云端模型分离主音吉他、节奏吉他和伴奏。
- 支持两种工作流：
  - `guitar_first`：先提取全部吉他，再拆分主音与节奏。
  - `direct`：直接使用 Lead/Rhythm Guitar 模型处理整曲。
- 每把吉他分别完成扒谱，并生成独立六线谱文件。
- 生成双吉他合并总谱，可在页面内查看五线谱与六线谱。
- 支持任务失败重试，并复用之前已完整下载的音轨。
- MVSEP 轮询、文件下载支持指数退避和断点续传。
- 需要 `MVSEP_API_TOKEN`；此模式会将音频上传到 MVSEP。

> MVSEP 免费账号通常只允许一个任务同时排队或处理，重复提交可能返回
> `400 Bad Request`。遇到这种情况应先等待远端队列完成，避免重复创建任务。

### MusicXML 与 MuseScore

- 页面使用 alphaTab 渲染五线谱和六线谱。
- 支持直接打印或另存为 PDF。
- MusicXML 使用完整 4/4 小节，避免 MuseScore 导入时自动挪动音符。
- 正确写入吉他调弦、弦号、品位和变调夹。
- 调弦行号遵循 MusicXML 规范，从最下方琴弦向上编号。
- 同时按起音时间和音高匹配指法，避免重复音高造成弦号/品位错配。
- 双吉他总谱使用独立 MIDI 通道，减少声部串音。

### 国内联网速查

- “伴奏”标签通过网易云音乐搜索国内伴奏、纯音乐、伴唱和去乐器版本。
- 只对有播放权限的结果显示试听地址。
- “曲谱”标签优先查询弹琴吧，并提供其他谱库入口。
- 可手动修改歌曲名与艺人后重新查询。
- 联网查询只发送歌曲名、艺人等检索词，不上传本地音频。

### 任务与界面

- 支持天蓝色/白色浅色主题与深绿/黄绿色深夜主题。
- 主题、图标和 favicon 会随模式切换，并保存在浏览器本地。
- 页面适配桌面和移动端。
- 使用 SSE 实时接收任务状态和进度。
- 最后打开的任务会写入浏览器本地记录。
- 刷新页面后会依次尝试恢复：
  1. 地址栏中的任务；
  2. 浏览器记录的最后任务；
  3. 服务器最近任务。
- `GET /api/jobs/recent` 聚合单吉他、整曲和分离任务。
- 任务快照写入磁盘，后端重启后仍可恢复结果。
- 后端重启时仍处于运行中的任务会被标记为中断，并保留重试入口。

> 仅选择但尚未点击“开始处理”的本地文件无法跨刷新保留，这是浏览器对本地文件
> 的安全限制。已经提交的任务会保存在服务器，可正常恢复。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、alphaTab |
| 后端 | FastAPI、Uvicorn、Pydantic |
| 本地分离 | Demucs、PyTorch、TorchAudio |
| 吉他识别 | Basic Pitch、TensorFlow |
| 乐谱处理 | music21、pretty_midi |
| 音频处理 | FFmpeg、ffprobe、SoundFile |
| 联网数据 | 网易云音乐、弹琴吧、MVSEP |

## 环境要求

- Windows 10/11
- Python 3.11
- Node.js 20+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg 与 ffprobe，并加入 `PATH`
- 可选：兼容 CUDA 13.0 的 NVIDIA 驱动

当前后端锁定 PyTorch/TorchAudio `2.9.1 + CUDA 13.0`。

## 快速开始

```powershell
cd "G:\python\poject\Audio separation"
.\setup.ps1
.\start.ps1
```

打开：

<http://127.0.0.1:8000>

首次使用某个 Demucs 模型时会自动下载权重，之后可复用本地缓存。

### 安装选项

使用清华 PyPI 镜像：

```powershell
.\setup.ps1
```

使用官方 PyPI：

```powershell
.\setup.ps1 -IndexUrl https://pypi.org/simple
```

只安装后端：

```powershell
.\setup.ps1 -SkipFrontend
```

## 启动与开发

生产构建模式：

```powershell
.\start.ps1
```

重新构建前端后启动：

```powershell
.\start.ps1 -RebuildFrontend
```

后端热重载：

```powershell
.\start.ps1 -Reload
```

分别启动前后端：

```powershell
cd backend
uv sync --extra dev
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm ci
npm run dev
```

开发服务器：

- 前端：<http://127.0.0.1:5173>
- 后端：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>

## 配置

复制环境变量模板：

```powershell
Copy-Item backend\.env.example backend\.env
```

### 常用配置

```dotenv
# 云端双吉他
MVSEP_API_TOKEN=your_token
MVSEP_WORKFLOW=guitar_first
MVSEP_MODEL_TYPE=1
MVSEP_OUTPUT_FORMAT=2
MVSEP_POLL_INTERVAL_SECONDS=3
MVSEP_POLL_RETRIES=5
MVSEP_JOB_TIMEOUT_SECONDS=3600
MVSEP_DOWNLOAD_RETRIES=5
MVSEP_DOWNLOAD_RETRY_DELAY_SECONDS=1.5
MVSEP_USE_ENV_PROXY=false

# 本地分离
DEMUCS_DEVICE=auto
DEMUCS_JOB_TIMEOUT_SECONDS=7200
```

`DEMUCS_DEVICE` 可选值：

- `auto`
- `cuda`
- `cpu`
- `mps`

修改 `.env` 后需要重启后端。

### 检查 CUDA

```powershell
.\backend\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

页面右上角会显示当前运行设备和引擎状态。

## 分离模型

| 模型 | 输出音轨 | 建议 |
| --- | --- | --- |
| `htdemucs` | 人声、鼓、贝斯、其他 | 默认，速度与内存较均衡 |
| `htdemucs_6s` | 人声、鼓、贝斯、吉他、钢琴、其他 | 指定吉他/钢琴伴奏 |
| `mdx_extra_q` | 人声、鼓、贝斯、其他 | 质量优先，CPU 较慢 |

处理质量对应的参数：

| 质量 | shifts | overlap |
| --- | --- | --- |
| 快速 | 0 | 0.1 |
| 均衡 | 1 | 0.25 |
| 高质量 | 2 | 0.5 |

AI 分离不是数学意义上的完美消除。混响、失真、声像重叠和相似频谱仍可能留下
少量串音。

## 隐私与数据流

- 本地分离与单吉他扒谱默认不向外部服务上传音频。
- 整曲双吉他会将音频上传至 MVSEP。
- 网易云音乐与弹琴吧查询只发送歌曲名、艺人等检索词。
- MVSEP Token 只保存在后端 `.env`，不会发送给浏览器。
- 下载第三方伴奏或曲谱时，请遵守对应平台条款与版权规则。

## 数据目录

```text
backend/data/jobs/
├── <job-id>/                    # 单吉他扒谱
├── songs/<job-id>/              # 整曲双吉他
└── separations/<job-id>/        # 本地分离
```

典型输出位置：

- 分离音轨：`backend/data/jobs/separations/<job-id>/stems/`
- 指定伴奏：`backend/data/jobs/separations/<job-id>/accompaniments/`
- 分离清单：`backend/data/jobs/separations/<job-id>/manifest.json`
- 单吉他谱：`backend/data/jobs/<job-id>/guitar.musicxml`
- 双吉他总谱：`backend/data/jobs/songs/<job-id>/guitar-score.musicxml`
- 前端构建：`frontend/dist/`

任务结果默认保留在磁盘，可根据需要人工清理。

## API

### 系统与搜索

- `GET /api/health`：运行时、设备和模型能力。
- `GET /api/jobs/recent`：最近的单吉他、整曲和分离任务。
- `POST /api/market/search`：国内伴奏、纯音乐和伴唱查询。
- `POST /api/scores/search`：中文曲谱与备用谱库查询。

### 单吉他扒谱

- `POST /api/transcriptions`：创建单吉他任务。
- `GET /api/transcriptions/{job_id}`：查询任务。
- `GET /api/transcriptions/{job_id}/events`：SSE 实时进度。
- `GET /api/transcriptions/{job_id}/audio`：原始音频。
- `GET /api/transcriptions/{job_id}/artifacts/{key}`：下载导出文件。

### 整曲双吉他

- `POST /api/song-transcriptions`：创建双吉他任务。
- `GET /api/song-transcriptions/{job_id}`：查询任务。
- `POST /api/song-transcriptions/{job_id}/retry`：重试任务。
- `GET /api/song-transcriptions/{job_id}/events`：SSE 实时进度。
- `GET /api/song-transcriptions/{job_id}/audio/{stem}`：试听音轨。
- `GET /api/song-transcriptions/{job_id}/guitars/{key}/artifacts/{artifact}`：
  下载单把吉他的 MIDI、MusicXML、TXT 或 JSON。
- `GET /api/song-transcriptions/{job_id}/score`：双吉他总谱。
- `GET /api/song-transcriptions/{job_id}/archive`：完整 ZIP。

### 本地分离

- `POST /api/separations`：创建分离与伴奏任务。
- `GET /api/separations/{job_id}`：查询任务。
- `GET /api/separations/{job_id}/events`：SSE 实时进度。
- `GET /api/separations/{job_id}/audio/source`：原曲。
- `GET /api/separations/{job_id}/audio/{stem|accompaniment}/{key}`：
  试听独立音轨或伴奏。
- `GET /api/separations/{job_id}/archive`：完整 ZIP。

## 测试

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

```powershell
cd frontend
npm run build
```

测试覆盖：

- 音频上传验证与任务状态持久化
- 本地分离、伴奏混音和 ZIP 打包
- MVSEP 轮询、断点下载与失败重试
- 单吉他与双吉他转录流程
- 最近任务恢复
- MusicXML 调弦、Capo、弦号、品位和音高一致性
- MIDI 导出

## 已知限制

- Basic Pitch 结果仍是 AI 初稿，复杂失真、快速扫弦和混响较重时可能需要人工修正。
- 本地分离效果依赖 Demucs 模型和原始混音质量。
- MVSEP 免费账号有并发和额度限制。
- 浏览器刷新无法恢复尚未提交的本地文件，需要重新选择。
- 当前六线谱统一使用 4/4 拍导出，复杂变拍歌曲可能需要人工调整。
- 暂不支持在页面内直接编辑弦号、品位或回写 MusicXML。

## 许可与致谢

项目代码遵循仓库许可证。

核心开源项目：

- [Demucs](https://github.com/facebookresearch/demucs)
- [Basic Pitch](https://github.com/spotify/basic-pitch)
- [alphaTab](https://www.alphatab.net/)
- [music21](https://www.music21.org/)
- [FFmpeg](https://ffmpeg.org/)
