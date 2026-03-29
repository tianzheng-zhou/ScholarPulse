# ScholarPulse — 需求文档

> 多平台聚合学术 AI 日报系统  
> 版本：v0.1 (草案)  
> 日期：2026-03-29

---

## 1. 项目概述

ScholarPulse 是一个面向个人学术工作者的**多平台学术论文聚合 + AI 摘要日报系统**。系统自动从多个学术数据源抓取与用户研究方向相关的最新论文，利用大语言模型进行摘要生成、相关性评分和中文翻译，最终以 Web 页面呈现每日学术日报。

**目标用户**：个人使用（单用户）  
**研究方向**：电子信息领域，侧重 TFT（薄膜晶体管）、神经形态计算等

---

## 2. 核心功能

### 2.1 多平台论文抓取

从以下数据源自动抓取论文，按关键词/领域筛选：

| # | 数据源 | 覆盖范围 | 接入方式 | 优先级 |
|---|---|---|---|---|
| 1 | **Semantic Scholar** | 全学科，2 亿+ 论文 | REST API（免费） | P0 |
| 2 | **arXiv** | 预印本（CS/物理/材料等） | arXiv API / OAI-PMH | P0 |
| 3 | **OpenAlex** | 全学科开放元数据 | REST API（免费） | P1 |
| 4 | **RSS 订阅** | 指定期刊（IEEE, Nature Electronics, Adv. Materials 等） | RSS/Atom Feed | P1 |

> **P0** = 首期必做；**P1** = 二期加入

### 2.2 AI 摘要与评分

- **摘要翻译**：将英文论文标题和摘要翻译为中文
- **一句话总结**：用一句话概括论文核心贡献
- **相关性评分**：根据用户配置的研究方向，对论文打 1-5 分相关性评分
- **关键词提取**：从论文中提取 3-5 个关键标签

### 2.3 日报展示

- 以「日」为单位组织论文，每天生成一期日报
- 按相关性评分排序，高分论文排前面
- 支持按数据源、评分、关键词筛选
- 论文卡片展示：标题（中英）、作者、来源、日期、AI 摘要、评分、原文链接

### 2.4 配置管理

- 关键词列表：支持增删改，用于各数据源的搜索和 AI 相关性评分
- 研究方向描述：一段自然语言描述，供 AI 判断相关性
- 数据源开关：可单独启用/禁用各数据源
- RSS 源管理：可添加/删除 RSS 订阅地址
- LLM 配置：API 地址、模型名称、API Key

---

## 3. 技术架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────┐
│                  Web 前端                     │
│           FastAPI + Jinja2 模板               │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────┴───────────────────────────┐
│                 后端服务                      │
│  ┌───────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ 抓取调度器 │ │ AI 处理器 │ │  API 路由   │ │
│  └─────┬─────┘ └────┬─────┘ └─────────────┘ │
│        │             │                        │
│  ┌─────┴─────────────┴──────────────────┐    │
│  │           数据库 (SQLite)              │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
        │
┌───────┴──────────────────────────────────────┐
│              数据源抓取器                      │
│  ┌────────────┐ ┌───────┐ ┌────────┐ ┌─────┐│
│  │Semantic Sch.│ │ arXiv │ │OpenAlex│ │ RSS ││
│  └────────────┘ └───────┘ └────────┘ └─────┘│
└──────────────────────────────────────────────┘
```

### 3.2 技术选型

| 组件 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 与现有工作区 .venv 一致 |
| Web 框架 | FastAPI | 轻量、异步、自带 API 文档 |
| 前端 | Jinja2 模板 + Tailwind CSS | 服务端渲染，简单直接 |
| 数据库 | SQLite | 个人使用，零运维，单文件 |
| ORM | SQLAlchemy 2.0 | 类型安全，async 支持 |
| 定时任务 | APScheduler | 进程内调度，不依赖外部 cron |
| HTTP 客户端 | httpx | 异步 HTTP 请求 |
| RSS 解析 | feedparser | 成熟的 RSS/Atom 解析库 |
| LLM 调用 | OpenAI SDK（兼容格式）| 支持 OpenAI / DeepSeek / 本地 Ollama 等任何 OpenAI 兼容 API |

### 3.3 目录结构

```
ScholarPulse/
├── docs/
│   └── requirements.md          # 本文档
├── scholarpulse/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置加载
│   ├── database.py              # 数据库初始化与模型定义
│   ├── fetchers/                # 数据源抓取器
│   │   ├── __init__.py
│   │   ├── base.py              # 抓取器基类
│   │   ├── semantic_scholar.py
│   │   ├── arxiv.py
│   │   ├── openalex.py
│   │   └── rss.py
│   ├── ai/                      # AI 处理模块
│   │   ├── __init__.py
│   │   └── summarizer.py        # 摘要、翻译、评分
│   ├── scheduler.py             # 定时调度
│   ├── routers/                 # API 路由
│   │   ├── __init__.py
│   │   ├── daily.py             # 日报页面
│   │   └── settings.py          # 设置页面
│   ├── templates/               # Jinja2 HTML 模板
│   │   ├── base.html
│   │   ├── daily.html           # 日报主页
│   │   ├── paper_detail.html    # 论文详情
│   │   └── settings.html        # 设置页面
│   └── static/                  # 静态资源
│       └── style.css
├── config.yaml                  # 用户配置文件
├── requirements.txt
└── README.md
```

---

## 4. 数据模型

### 4.1 论文 (papers)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| source | TEXT | 数据来源：semantic_scholar / arxiv / openalex / rss |
| source_id | TEXT | 原始平台 ID（用于去重） |
| title | TEXT | 英文标题 |
| title_zh | TEXT | 中文标题（AI 翻译） |
| authors | TEXT | 作者列表（JSON） |
| abstract | TEXT | 英文摘要 |
| summary_zh | TEXT | 中文一句话总结（AI 生成） |
| relevance_score | REAL | 相关性评分 1-5（AI 打分） |
| keywords | TEXT | AI 提取的关键词（JSON） |
| url | TEXT | 原文链接 |
| published_date | DATE | 发表/预印日期 |
| fetched_at | DATETIME | 抓取时间 |
| ai_processed | BOOLEAN | 是否已完成 AI 处理 |
| journal | TEXT | 期刊/会议名（可选） |
| doi | TEXT | DOI（可选） |

**唯一约束**：`(source, source_id)` 防止重复抓取

### 4.2 抓取日志 (fetch_logs)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| source | TEXT | 数据源 |
| started_at | DATETIME | 开始时间 |
| finished_at | DATETIME | 结束时间 |
| papers_found | INTEGER | 发现论文数 |
| papers_new | INTEGER | 新增论文数（去重后） |
| status | TEXT | success / error |
| error_message | TEXT | 错误信息（如有） |

---

## 5. 数据源接入细节

### 5.1 Semantic Scholar

- **API**：`https://api.semanticscholar.org/graph/v1/paper/search`
- **认证**：无 Key 可用（100 次/5 分钟），注册 API Key 后 100 次/1 秒
- **查询方式**：按关键词搜索，按日期范围筛选
- **返回字段**：title, abstract, authors, year, externalIds, url, publicationDate

### 5.2 arXiv

- **API**：`http://export.arxiv.org/api/query`
- **认证**：无需
- **查询方式**：按关键词 + 分类（cat:cs.ET, cat:cs.NE 等）搜索
- **返回字段**：title, summary, authors, published, links, categories

### 5.3 OpenAlex

- **API**：`https://api.openalex.org/works`
- **认证**：无需（建议设 `mailto` 参数提升速率）
- **查询方式**：按 concept/keyword + 日期范围筛选
- **返回字段**：title, abstract_inverted_index, authorships, doi, publication_date

### 5.4 RSS

- **解析**：feedparser 库
- **流程**：按配置的 RSS URL 列表轮询，解析 entry 中的 title/summary/link/published
- **预配置源**（示例）：
  - IEEE Electron Device Letters
  - Nature Electronics
  - Advanced Electronic Materials
  - Neuromorphic Computing and Engineering

---

## 6. AI 处理流程

### 6.1 Prompt 设计

对每篇论文，发送一次 LLM 请求，Prompt 结构：

```
你是一位电子信息领域的学术助手。用户的研究方向是：{research_description}
用户关注的关键词：{keywords_list}

请分析以下论文：
标题：{title}
摘要：{abstract}

请返回 JSON 格式：
{
  "title_zh": "中文标题",
  "summary_zh": "一句话中文总结（30字以内）",
  "relevance_score": 4,
  "relevance_reason": "简述为什么给这个分数",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}
```

### 6.2 批处理策略

- 抓取完成后，对 `ai_processed = false` 的论文批量处理
- 并发控制：最多 5 个并发请求，避免触发 API 限速
- 失败重试：最多 3 次，指数退避

### 6.3 LLM 后端兼容

通过 OpenAI SDK 的 `base_url` 配置，支持：
- OpenAI（gpt-4o-mini 等）
- DeepSeek（deepseek-chat）
- 本地 Ollama（http://localhost:11434/v1）
- 其他 OpenAI 兼容 API

---

## 7. Web 界面

### 7.1 页面列表

| 页面 | 路径 | 功能 |
|---|---|---|
| 日报主页 | `/` | 展示今日论文列表，按相关性排序 |
| 历史日报 | `/daily/{date}` | 查看指定日期的日报 |
| 论文详情 | `/paper/{id}` | 单篇论文的完整信息 |
| 设置 | `/settings` | 关键词、数据源、LLM 配置 |
| 手动抓取 | `/fetch` (POST) | 手动触发一次全量抓取 |

### 7.2 日报主页设计

```
┌──────────────────────────────────────────────────┐
│  ScholarPulse                    ← 2026-03-29 →  │
│  ─────────────────────────────────────────────── │
│  [全部] [Semantic Scholar] [arXiv] [RSS]   🔍搜索│
│  ─────────────────────────────────────────────── │
│  ★★★★★ (5.0)                                     │
│  基于 IGZO TFT 的突触晶体管实现神经形态计算       │
│  Synaptic Transistor Based on IGZO TFT for...    │
│  作者: Zhang et al. | Nature Electronics | 今天   │
│  AI 摘要: 提出了一种新型 IGZO 基突触晶体管...      │
│  #TFT #neuromorphic #IGZO                        │
│  [查看原文↗]                                      │
│  ─────────────────────────────────────────────── │
│  ★★★★☆ (4.0)                                     │
│  ...                                             │
└──────────────────────────────────────────────────┘
```

### 7.3 UI 风格

- 简洁学术风，深色/浅色主题可选
- Tailwind CSS，响应式布局
- 无需前端框架，服务端渲染即可

---

## 8. 配置文件 (config.yaml)

```yaml
# ScholarPulse 配置文件

# 研究方向描述（供 AI 评估相关性）
research_description: |
  我的研究方向是电子信息领域，主要关注：
  1. 薄膜晶体管（TFT），特别是氧化物半导体 TFT（如 IGZO）
  2. 神经形态计算，包括突触器件、忆阻器、存内计算
  3. 柔性电子器件

# 搜索关键词
keywords:
  - "thin-film transistor"
  - "TFT"
  - "IGZO"
  - "neuromorphic computing"
  - "synaptic transistor"
  - "memristor"
  - "in-memory computing"
  - "oxide semiconductor"
  - "flexible electronics"

# 数据源配置
sources:
  semantic_scholar:
    enabled: true
    api_key: ""  # 可选，不填则用免费额度
  arxiv:
    enabled: true
    categories:
      - "cs.ET"       # 新兴技术
      - "cs.NE"       # 神经进化计算
      - "cs.AR"       # 计算机体系结构
      - "cond-mat.mtrl-sci"  # 材料科学
      - "physics.app-ph"     # 应用物理
  openalex:
    enabled: false  # 二期开启
    email: ""       # 用于 polite pool
  rss:
    enabled: false  # 二期开启
    feeds:
      - name: "Nature Electronics"
        url: "https://www.nature.com/natelectron.rss"
      - name: "IEEE Electron Device Letters"
        url: ""  # 需填入实际 RSS URL
      - name: "Advanced Electronic Materials"
        url: ""

# LLM 配置
llm:
  base_url: "https://api.openai.com/v1"  # 或 DeepSeek / Ollama 地址
  api_key: ""
  model: "gpt-4o-mini"  # 或 deepseek-chat / llama3 等
  max_concurrent: 5

# 调度配置
scheduler:
  enabled: true
  cron: "0 8 * * *"  # 每天早上 8 点执行
  fetch_days: 3       # 每次抓取最近 N 天的论文

# Web 服务
server:
  host: "127.0.0.1"
  port: 8080
```

---

## 9. 开发计划

### 第一期（MVP）

- [x] 需求文档
- [ ] 项目骨架搭建（目录、配置、依赖）
- [ ] SQLite 数据库层
- [ ] Semantic Scholar 抓取器
- [ ] arXiv 抓取器
- [ ] AI 摘要/评分模块
- [ ] 定时调度器
- [ ] Web 日报页面（列表 + 详情 + 筛选）
- [ ] 设置页面（关键词、LLM 配置）

### 第二期

- [ ] OpenAlex 抓取器
- [ ] RSS 抓取器
- [ ] 论文去重优化（跨数据源 DOI 匹配）
- [ ] 邮件推送
- [ ] 深色主题
- [ ] 论文收藏/标记已读功能
- [ ] 数据导出（Markdown / CSV）

### 第三期（可选）

- [ ] 基于引用关系的推荐（"看了这篇的人也看了..."）
- [ ] 作者追踪（关注特定课题组）
- [ ] 全文 PDF 下载与本地存储
- [ ] 移动端适配

---

## 10. 待确认项

> 请确认或修改以下内容：

1. **LLM 选择**：你打算用哪个 LLM？OpenAI / DeepSeek / 本地 Ollama？
2. **关键词列表**：上面的关键词列表是否需要调整？
3. **RSS 源**：有没有特别想订阅的期刊？
4. **调度时间**：每天早上 8 点跑合适吗？
5. **部署方式**：纯本地运行还是会部署到云服务器？
6. **其他需求**：有没有我遗漏的功能？
