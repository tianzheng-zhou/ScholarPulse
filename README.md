# ScholarPulse

> 多平台聚合学术 AI 日报系统

自动从 Semantic Scholar、arXiv 等学术数据源抓取与研究方向相关的最新论文，利用大语言模型进行摘要翻译、相关性评分和关键词提取，以 Web 页面呈现每日学术日报。

## 功能特性

- 📡 **多平台论文抓取**：Semantic Scholar + arXiv（可扩展 OpenAlex、IEEE Xplore、RSS 等）
- 🤖 **AI 智能处理**：中文翻译、一句话总结、1-5 相关性评分、关键词提取
- 📊 **期刊分级标签**：中科院分区、JCR 分区、影响因子显示
- 📰 **日报展示**：按日浏览、按评分排序、多维筛选
- ⚙️ **灵活配置**：关键词、数据源、LLM 模型均可自定义
- ⏰ **定时调度**：自动每日抓取 + AI 处理

## 快速开始

### 1. 安装依赖

```bash
cd ScholarPulse
pip install -r requirements.txt
```

### 2. 配置 API Key

复制环境变量模板并填入 API Key：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入阿里云百炼 API Key：

```
DASHSCOPE_API_KEY=your_actual_api_key
```

### 3. 调整配置（可选）

编辑 `config.yaml` 自定义研究方向、关键词、数据源等。

### 4. 启动服务

```bash
uvicorn scholarpulse.main:app --host 127.0.0.1 --port 15471 --reload
```

打开浏览器访问 http://127.0.0.1:15471

## 使用说明

| 页面 | 路径 | 功能 |
|---|---|---|
| 日报主页 | `/` | 展示今日论文，按相关性排序 |
| 历史日报 | `/daily/{date}` | 查看指定日期的日报 |
| 论文详情 | `/paper/{id}` | 单篇论文完整信息 |
| 设置 | `/settings` | 关键词、数据源、LLM 配置 |
| 手动抓取 | 日报页面点击按钮 | 手动触发抓取 |
| 抓取日志 | `/logs` | 查看历史抓取记录 |

## 项目结构

```
ScholarPulse/
├── config.yaml              # 用户配置
├── .env                     # API Key（不提交版本控制）
├── requirements.txt
├── scholarpulse/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置加载
│   ├── database.py          # 数据库模型
│   ├── journal_ranks.py     # 期刊分级映射表
│   ├── scheduler.py         # 定时调度
│   ├── fetchers/            # 数据源抓取器
│   │   ├── base.py          # 抓取器基类
│   │   ├── semantic_scholar.py
│   │   └── arxiv.py
│   ├── ai/
│   │   └── summarizer.py    # AI 摘要/评分
│   ├── routers/
│   │   ├── daily.py         # 日报路由
│   │   └── settings.py      # 设置路由
│   ├── templates/           # Jinja2 模板
│   └── static/              # 静态资源
└── docs/
    └── requirements.md      # 需求文档
```

## 技术栈

- **后端**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 / SQLite
- **前端**: Jinja2 + Tailwind CSS（服务端渲染）
- **AI**: 阿里云百炼 qwen3.5-plus（OpenAI 兼容接口）
- **调度**: APScheduler

## License

MIT
