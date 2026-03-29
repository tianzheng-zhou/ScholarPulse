# ScholarPulse — 需求文档

> 多平台聚合学术 AI 日报系统  
> 版本：v0.2 (需求确认)  
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
| 5 | **IEEE Xplore** | IEEE 全文数据库（EDL, TED, JEDS 等核心期刊） | REST API（需申请 Key，免费 200次/天） | P1 |
| 6 | **CrossRef** | DOI 元数据与引用数据 | REST API（免费，polite pool） | P1（辅助层） |

> **P0** = 首期必做；**P1** = 二期加入  
> CrossRef 定位为辅助工具层，用于跨源去重增强、获取引用数和期刊元数据补全，不作为主要论文抓取源

### 2.2 AI 摘要与评分

- **摘要翻译**：将英文论文标题和摘要翻译为中文
- **一句话总结**：用一句话概括论文核心贡献（仅基于摘要内容）
- **相关性评分**：根据用户配置的研究方向，对论文打 1-5 分相关性评分
- **关键词提取**：从论文中提取 3-5 个关键标签
- **失败处理**：AI 处理失败的论文在日报中显示为「未处理」状态，不隐藏

### 2.3 日报展示

- 以「日」为单位组织论文，每天生成一期日报
- 按相关性评分排序，高分论文排前面
- 支持按数据源、评分、关键词筛选
- 论文卡片展示：标题（中英）、作者、来源、日期、AI 摘要、评分、期刊等级标签、原文链接

### 2.4 配置管理

- 关键词列表：支持增删改，用于各数据源的搜索和 AI 相关性评分
- 研究方向描述：一段自然语言描述，供 AI 判断相关性
- 数据源开关：可单独启用/禁用各数据源
- RSS 源管理：可添加/删除 RSS 订阅地址
- LLM 配置：API 地址、模型名称（API Key 通过 .env 文件管理）

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
│  ┌────────────┐ ┌─────────┐                  │
│  │IEEE Xplore │ │CrossRef │ (辅助层)         │
│  └────────────┘ └─────────┘                  │
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
| LLM 调用 | OpenAI SDK（兼容格式）| 通过阿里云百炼 OpenAI 兼容接口调用 qwen3.5-plus |

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
│   │   ├── openalex.py│   │   ├── ieee_xplore.py
│   │   ├── crossref.py          # 辅助：元数据补全与引用数│   │   └── rss.py
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
├── .env                         # 敏感配置（API Key 等），不纳入版本控制
├── .env.example                 # .env 模板，纳入版本控制
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
| journal_rank | TEXT | 期刊等级标签，如 "Q1"、"中科院1区"（JSON，可选） |
| citation_count | INTEGER | 被引次数（来自 Semantic Scholar / CrossRef，可选） |
| doi | TEXT | DOI（可选） |

**唯一约束**：`(source, source_id)` 防止重复抓取

**跨源去重**：第一期即实现基于 DOI 的跨数据源去重，同一篇论文优先保留最先抓取到的记录

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
- **认证**：无 API Key，使用免费额度（100 次/5 分钟），需做好请求间隔控制
- **查询方式**：按关键词搜索，按日期范围筛选
- **返回字段**：title, abstract, authors, year, externalIds, url, publicationDate

### 5.2 arXiv

- **API**：`http://export.arxiv.org/api/query`
- **认证**：无需
- **查询方式**：将多个关键词用 OR 组合为一个查询 + 分类（cat:cs.ET, cat:cs.NE 等）筛选，减少请求次数
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

### 5.5 IEEE Xplore

- **API**：`https://ieeexploreapi.ieee.org/api/v1/search/articles`
- **认证**：需申请 API Key（免费，200 次/天）
- **查询方式**：按关键词 + 日期范围搜索，支持按期刊筛选
- **返回字段**：title, abstract, authors, publication_title, doi, publication_date
- **核心价值**：该领域核心期刊（IEEE EDL, IEEE TED, IEEE JEDS 等）均在 IEEE，是 TFT/神经形态计算研究的主要发表渠道

### 5.6 CrossRef（辅助层）

- **API**：`https://api.crossref.org/works`
- **认证**：无需（建议设 `mailto` 参数进入 polite pool，提升速率）
- **用途**：
  - 跨源去重增强：通过 DOI 查询规范化元数据
  - 获取引用次数（`is-referenced-by-count`）
  - 期刊元数据补全（ISSN → 期刊名、出版商等）
- **返回字段**：DOI, title, author, container-title, is-referenced-by-count, published-date

---

## 6. 论文质量评估

### 6.1 评估维度

对于近年新发表的论文（引用量尚未积累），通过以下维度综合评估质量：

| 维度 | 指标 | 数据来源 | 说明 |
|---|---|---|---|
| **期刊等级** | 中科院分区 | 本地映射表 | 国内学术界最常用，1-4 区，1 区为顶刊 |
| | JCR 分区 | 本地映射表 | Q1-Q4，与影响因子挂钩 |
| | 影响因子 (IF) | 本地映射表 | 期刊级别指标，如 Nature Electronics IF≈30+ |
| **论文信号** | 被引次数 | Semantic Scholar / CrossRef | 近期论文参考价值有限 |
| | 有影响力引用数 | Semantic Scholar `influentialCitationCount` | 区分一般引用和深度引用 |
| **作者信号** | 作者 h-index | Semantic Scholar / OpenAlex | 知名课题组论文通常质量较高 |

### 6.2 期刊分级映射表

维护一个本地期刊分级映射表（`journal_rankings`），覆盖本领域常见期刊：

| 期刊名 | 中科院分区 | JCR 分区 | IF（近似） |
|---|---|---|---|
| Nature Electronics | 1区 | Q1 | 30+ |
| Advanced Materials | 1区 | Q1 | 28+ |
| IEEE Electron Device Letters (EDL) | 2区 | Q1 | 4+ |
| IEEE Trans. Electron Devices (TED) | 3区 | Q2 | 3+ |
| Advanced Electronic Materials | 2区 | Q1 | 6+ |
| Neuromorphic Computing and Engineering | - | Q2 | 3+ |

> 此表可通过设置页面手动维护，也可后续接入 OpenAlex venue 数据自动补全。

### 6.3 落地方案

1. **期刊等级标签**：论文卡片上显示期刊分区标签（如 `Q1`、`中科院1区`）
2. **Semantic Scholar 元数据**：抓取时获取 `citationCount`、`influentialCitationCount` 并存入数据库
3. **AI 综合评分**：在 prompt 中将期刊名传给 AI，让其在评估相关性时也参考发表刊物的层级
4. **综合排序**：默认排序权重 = `相关性评分 × 期刊权重因子`，期刊权重可配置

---

## 7. AI 处理流程

### 7.1 Prompt 设计

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

### 7.2 批处理策略

- 抓取完成后，对 `ai_processed = false` 的论文批量处理
- 并发控制：最多 5 个并发请求，避免触发 API 限速
- 失败重试：最多 3 次，指数退避

### 7.3 LLM 后端

当前使用阿里云百炼平台的 **qwen3.5-plus** 模型，通过 OpenAI SDK 的 `base_url` 配置接入：
- base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- 模型名: `qwen3.5-plus`
- API Key: 通过 `.env` 文件中的 `DASHSCOPE_API_KEY` 环境变量配置
- 使用非思考模式（`enable_thinking: false`）以降低成本

架构上仍兼容其他 OpenAI 兼容 API（OpenAI / DeepSeek / Ollama 等），只需修改 `config.yaml` 中的 `base_url` 和 `model` 即可切换。

---

## 8. Web 界面

### 8.1 页面列表

| 页面 | 路径 | 功能 |
|---|---|---|
| 日报主页 | `/` | 展示今日论文列表，按相关性排序 |
| 历史日报 | `/daily/{date}` | 查看指定日期的日报 |
| 论文详情 | `/paper/{id}` | 单篇论文的完整信息 |
| 设置 | `/settings` | 关键词、数据源、LLM 配置 |
| 手动抓取 | `/fetch` (POST) | 手动触发抓取，支持指定时间范围 |

### 8.2 日报主页设计

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
│  [Q1] [中科院1区] [IF: 30.2]                      │
│  AI 摘要: 提出了一种新型 IGZO 基突触晶体管...      │
│  #TFT #neuromorphic #IGZO                        │
│  [查看原文↗]                                      │
│  ─────────────────────────────────────────────── │
│  ★★★★☆ (4.0)                                     │
│  ...                                             │
└──────────────────────────────────────────────────┘
```

### 8.3 UI 风格

- 简洁学术风，深色/浅色主题可选
- Tailwind CSS，响应式布局
- 无需前端框架，服务端渲染即可

---

## 9. 配置文件 (config.yaml)

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
    # 无 API Key，使用免费额度（100 次/5分钟）
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
  ieee_xplore:
    enabled: false  # 二期开启
    # api_key 通过 .env 文件中的 IEEE_API_KEY 配置
  crossref:
    enabled: false  # 二期开启，辅助层
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
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  # api_key 通过 .env 文件中的 DASHSCOPE_API_KEY 配置
  model: "qwen3.5-plus"
  max_concurrent: 5
  enable_thinking: false  # 非思考模式，降低成本

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

## 10. 开发计划

### 第一期（MVP）

- [x] 需求文档
- [ ] 项目骨架搭建（目录、配置、依赖）
- [ ] SQLite 数据库层（含 journal_rank、citation_count 字段）
- [ ] Semantic Scholar 抓取器（含 citationCount 获取）
- [ ] arXiv 抓取器
- [ ] 期刊分级映射表（本地维护）
- [ ] AI 摘要/评分模块
- [ ] 定时调度器
- [ ] Web 日报页面（列表 + 详情 + 筛选 + 期刊等级标签）
- [ ] 设置页面（关键词、LLM 配置）

### 第二期

- [ ] OpenAlex 抓取器
- [ ] RSS 抓取器
- [ ] IEEE Xplore 抓取器
- [ ] CrossRef 辅助层（引用数获取、元数据补全）
- [ ] 论文去重优化（跨数据源 DOI 匹配）
- [ ] 期刊映射表扩展（接入 OpenAlex venue 数据自动补全）
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

## 11. 已确认事项

| # | 问题 | 决定 |
|---|---|---|
| 1 | LLM 选择 | 阿里云百炼 **qwen3.5-plus**，通过 OpenAI 兼容接口调用 |
| 2 | LLM 接入 | base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`，API Key 环境变量: `DASHSCOPE_API_KEY` |
| 3 | LLM 成本 | 输入 0.8 元/百万 Token，输出 4.8 元/百万 Token（≤128K），新用户有 100 万 Token 免费额度 |
| 4 | 关键词列表 | 保持现有列表不变 |
| 5 | 调度时间 | 默认每天 8 点 |
| 6 | 部署方式 | 暂时本地运行，后续可能上服务器 |
| 7 | Semantic Scholar | 无 API Key，使用免费额度，做好限速控制 |
| 8 | 跨源去重 | 第一期即通过 DOI 实现跨数据源去重 |
| 9 | 手动抓取 | 前端页面提供按钮 + 可选时间范围 |
| 10 | AI 失败处理 | 论文显示为「未处理」，不隐藏 |
| 11 | AI 处理范围 | 仅总结摘要中的内容 |
| 12 | 敏感配置 | API Key 等放 `.env` 文件，其余放 `config.yaml` |
