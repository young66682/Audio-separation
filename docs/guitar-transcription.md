# 吉他扒谱

这个模块可以把整首歌分离为主音吉他、节奏吉他和伴奏，再分别生成两套六线谱；也可以在不上传音频的情况下，直接转录已有的 guitar stem。它已与本地 Demucs 分离、指定乐器伴奏工作台整合在同一个 FastAPI + Vue 应用中。

## 两种工作模式

### 整曲双吉他

```text
整首歌曲
  → MVSEP 高精度全吉他隔离
  → MVSEP Lead/Rhythm Guitar 拆分
  → lead / rhythm / backing
  → Basic Pitch 分别转录
  → 主音吉他谱 + 节奏吉他谱 + 整套 ZIP
```

这个模式需要免费的 MVSEP API Token。MVSEP 官方套餐目前提供：

- 每天 50 次免费分离
- 单曲最长 10 分钟
- 最大 100 MB
- 一个并发任务

使用该模式时，整首歌曲会上传到 MVSEP 服务器。Token 只保存在后端，不会发送给浏览器。

默认流水线会执行两次分离，比直接把整曲送入 Lead/Rhythm 模型更完整，但大约消耗两次每日额度。额度紧张时可以在 `backend/.env` 设置：

```dotenv
MVSEP_WORKFLOW=direct
```

### 单吉他音轨

完全在本地处理已经分离的 guitar stem 或独奏录音，不需要 MVSEP 账号。

## 功能

- MVSEP 高精度全吉他隔离，再拆分主音/节奏吉他
- Basic Pitch 多音高识别
- 自动测速或手动指定 BPM
- 标准、Drop D、降半音、Open G、DADGAD 调弦
- 变调夹与最大品数约束
- 同一时间音符自动分配到不同琴弦
- 十六分音符网格量化
- 吉他音轨响度标准化
- 泛音重复过滤、力度门槛与和弦跨度限制
- 默认限制到 17 品和 5 品和弦跨度，减少不可演奏把位
- 每把吉他分别导出六线谱 TXT、MIDI、MusicXML 和音符 JSON
- SSE 实时进度、音频试听、点击六线谱定位

## 配置 MVSEP

复制示例配置：

```powershell
cd backend
Copy-Item .env.example .env
```

编辑 `backend/.env`，填写从 [MVSEP Plans](https://mvsep.com/plans) 注册后获取的 API Token：

```dotenv
MVSEP_API_TOKEN=your_api_token_here
```

修改 `.env` 后必须重启后端。不要提交真实 Token，`.gitignore` 已排除 `backend/.env`。

## 环境

Basic Pitch 0.4.0 依赖 TensorFlow `<2.15.1`，因此后端固定使用 Python 3.11。项目根目录现有的 Python 3.13 环境继续用于 Streamlit 和 Demucs。

```powershell
cd backend
$env:UV_SYSTEM_CERTS='true'
uv python install 3.11
uv sync --extra dev --python 3.11
```

`UV_SYSTEM_CERTS` 用于当前机器的企业证书环境。项目已锁定 `numpy==1.26.4`、TensorFlow 2.14 和 Basic Pitch 0.4，避免 TensorFlow 与 NumPy 2.x 的二进制兼容问题。

## 启动

后端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端开发模式：

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。API 文档位于 `http://127.0.0.1:8000/docs`。

“整曲双吉他”页面会显示云端是否已配置。未填写 Token 时，该模式会被禁用，但“单吉他音轨”仍可正常使用。

## 构建单页应用

```powershell
cd frontend
npm run build
```

重新启动 FastAPI 后，后端会自动托管 `frontend/dist`，直接访问 `http://127.0.0.1:8000`。

## 准确率说明

MVSEP 对主音在中间、节奏吉他在左右声像的混音效果通常更好。强烈失真、长延时、重混响或两把居中同音色吉他会增加串音。结果仍是扒谱初稿，发布前应人工检查：

- 主音吉他和节奏吉他的标签是否互换
- 两把吉他是否互相串音
- 快速音符是否被合并
- 和弦是否分配到更符合演奏习惯的把位
- BPM、拍号和切分音是否需要校正

下一阶段可以在现有 `events` 数据结构上增加人工拖动音符、修改弦/品、撤销重做和 MusicXML 回写。
