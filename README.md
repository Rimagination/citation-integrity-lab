# 引文深度核查工具（Web）

基于 `jiansuo/检索prd.md` 实现的可部署网页应用：

- 单输入框粘贴正文 + 参考文献
- 自动识别正文引用锚点（`[1]` / `(Author, Year)`）
- 三维核验：元数据真伪、语境相关性、断言支持度
- 点击高亮标签查看右侧诊断卡片（官方元数据、冲突对比、支持度雷达）

## 1. 本地运行

```bash
cd jiansuo
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000`。

## 2. API 概览

- `POST /api/parse`：解析正文与参考文献、提取锚点
- `POST /api/verify/metadata`：对参考文献做 Crossref/OpenAlex 元数据核验
- `POST /api/verify/support`：断言支持度判定（claim + abstract）
- `POST /api/analyze`：一键完整核查（前端主入口）

## 3. 对外发布（给别人链接直接用）

可以直接部署到 Render / Railway / Fly.io / 云服务器。

### Render 示例

1. 新建 Web Service，连接代码仓库。
2. 设置：
   - Build Command: `pip install -r jiansuo/requirements.txt`
   - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - Root Directory: `jiansuo`
3. 部署完成后会得到 `https://xxxx.onrender.com`，把这个链接发给别人即可使用。

## 4. 当前实现说明

- 元数据核验使用 Crossref + OpenAlex 双源检索。
- “相关性 / 支持度”采用轻量启发式语义算法（无需额外模型下载，开箱可跑）。
- 如果后续你需要更强的 NLI，可在 `backend/verification.py` 接入云端 LLM 推理替换对应函数。

