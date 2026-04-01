"""向量嵌入与重排序模块

使用 qwen3-vl-embedding 生成向量，qwen3-vl-rerank 进行语义重排序。
通过 DashScope HTTP API 调用（多模态向量 / 重排序接口不走 OpenAI 兼容层）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "qwen3-vl-embedding"
RERANK_MODEL = "qwen3-vl-rerank"
EMBEDDING_DIM = 2560
EMBEDDING_BATCH_SIZE = 20  # 每批次文本数（API 上限 20，拉满）

EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/"
    "text-rerank/text-rerank"
)

# 复用连接池的全局 httpx 客户端
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=80,
                max_keepalive_connections=40,
            ),
        )
    return _http_client


def _api_key() -> str:
    return os.getenv("DASHSCOPE_API_KEY", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


# ── Embedding ──────────────────────────────────────────


async def generate_embedding(
    text: str,
    *,
    instruct: str = "",
) -> list[float] | None:
    """为单条文本生成向量。"""
    if not _api_key():
        logger.warning("DASHSCOPE_API_KEY 未设置，跳过向量生成")
        return None

    params: dict[str, Any] = {"dimension": EMBEDDING_DIM}
    if instruct:
        params["instruct"] = instruct

    try:
        client = _get_client()
        resp = await client.post(
            EMBEDDING_URL,
            headers=_headers(),
            json={
                "model": EMBEDDING_MODEL,
                "input": {"contents": [{"text": text}]},
                "parameters": params,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Embedding API 调用失败")
        return None

    if data.get("code"):
        logger.error(
            "Embedding API error: %s - %s", data["code"], data.get("message")
        )
        return None

    embeddings = data.get("output", {}).get("embeddings", [])
    if embeddings:
        return embeddings[0]["embedding"]
    return None


async def generate_embeddings_batch(
    texts: list[str],
    *,
    instruct: str = "",
    max_concurrent: int = 30,
) -> list[list[float] | None]:
    """批量生成向量。每 EMBEDDING_BATCH_SIZE 条一个 API 请求，高并发复用连接池。"""
    if not _api_key():
        logger.warning("DASHSCOPE_API_KEY 未设置，跳过向量生成")
        return [None] * len(texts)

    results: list[list[float] | None] = [None] * len(texts)
    semaphore = asyncio.Semaphore(max_concurrent)

    params: dict[str, Any] = {"dimension": EMBEDDING_DIM}
    if instruct:
        params["instruct"] = instruct

    client = _get_client()

    async def _batch(start: int, batch_texts: list[str]) -> None:
        async with semaphore:
            try:
                resp = await client.post(
                    EMBEDDING_URL,
                    headers=_headers(),
                    json={
                        "model": EMBEDDING_MODEL,
                        "input": {
                            "contents": [{"text": t} for t in batch_texts]
                        },
                        "parameters": params,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("Embedding batch %d 调用失败", start)
                return

            if data.get("code"):
                logger.error(
                    "Embedding batch error: %s - %s",
                    data["code"], data.get("message"),
                )
                return

            for emb in data.get("output", {}).get("embeddings", []):
                idx = emb["index"]
                results[start + idx] = emb["embedding"]

    tasks = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        tasks.append(_batch(i, batch))

    await asyncio.gather(*tasks)
    return results


# ── Rerank ─────────────────────────────────────────────


async def rerank(
    query: str,
    documents: list[str],
    top_n: int = 20,
    instruct: str = (
        "Given a web search query, retrieve relevant passages that answer the query."
    ),
) -> list[dict[str, Any]]:
    """使用 qwen3-vl-rerank 对候选文档重新排序。

    返回 [{"index": int, "relevance_score": float}, ...]，按分数降序。
    """
    if not documents:
        return []
    if not _api_key():
        logger.warning("DASHSCOPE_API_KEY 未设置，跳过重排序")
        return []

    # qwen3-vl-rerank 最多 100 篇文档
    docs = documents[:100]

    try:
        client = _get_client()
        resp = await client.post(
            RERANK_URL,
            headers=_headers(),
            json={
                "model": RERANK_MODEL,
                "input": {
                    "query": {"text": query},
                    "documents": [{"text": d} for d in docs],
                },
                "parameters": {
                    "top_n": min(top_n, len(docs)),
                    "return_documents": False,
                    "instruct": instruct,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Rerank API 调用失败")
        return []

    if data.get("code"):
        logger.error(
            "Rerank API error: %s - %s", data["code"], data.get("message")
        )
        return []

    return data.get("output", {}).get("results", [])


# ── 向量序列化 ─────────────────────────────────────────


def serialize_embedding(embedding: list[float]) -> bytes:
    """将向量序列化为 bytes，用于存储到 BLOB 列。"""
    return struct.pack(f"{len(embedding)}f", *embedding)


def deserialize_embedding(data: bytes) -> list[float]:
    """从 bytes 反序列化向量。"""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


# ── 相似度计算 ─────────────────────────────────────────


def cosine_similarity_batch(
    query_vec: list[float],
    embeddings: list[list[float]],
) -> list[float]:
    """计算 query 与一组向量的余弦相似度。"""
    if not embeddings:
        return []
    q = np.array(query_vec, dtype=np.float32)
    mat = np.array(embeddings, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm < 1e-10:
        return [0.0] * len(embeddings)
    mat_norms = np.linalg.norm(mat, axis=1)
    mat_norms = np.maximum(mat_norms, 1e-10)
    sims = (mat @ q) / (mat_norms * q_norm)
    return sims.tolist()


def build_paper_text(title: str, abstract: str | None) -> str:
    """构造用于向量化的论文文本：标题 + 摘要。"""
    text = title
    if abstract:
        text += ". " + abstract[:3000]
    return text
