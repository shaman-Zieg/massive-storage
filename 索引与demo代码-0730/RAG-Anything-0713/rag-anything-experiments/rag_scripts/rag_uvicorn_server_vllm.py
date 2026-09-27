"""
example shows how to:
1. Process documents with RAGAnything using MinerU parser
2. Perform pure text queries using aquery() method
3. Perform multimodal queries with specific multimodal content using aquery_with_multimodal() method
4. Handle different types of multimodal content (tables, equations) in queries
"""

import os
import sys
import logging
import logging.config
from pathlib import Path
from contextlib import asynccontextmanager
from itertools import cycle
from typing import Any, Optional
from datetime import datetime
import time
import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Add project root directory to Python path
sys.path.append(str(Path(__file__).parent.parent))

from lightrag import QueryParam
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc, logger, set_verbose_debug
# from lightrag.llm.ollama import ollama_embed
from raganything import RAGAnything, RAGAnythingConfig

dotenv_file = os.getenv('DOTENV_FILE', '')
load_dotenv(dotenv_path=dotenv_file, override=True)

import traceback

# =========================
# OpenAI-compatible 配置
# =========================
# API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "").rstrip("/")

LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")
LLM_API_KEY = os.getenv("LLM_MODEL_API_KEY") or os.getenv(
    "LLM_BINDING_API_KEY", "api-key"
)
VLLM_API_KEY = os.getenv("VLLM_MODEL_API_KEY") or os.getenv(
    "VLLM_BINDING_API_KEY", "api-key"
)
VLLM_MODEL  = os.getenv("VLLM_MODEL", "qwen3.5-plus")
VLLM_BINDING_API_KEY = VLLM_API_KEY
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_BINDING_HOST = os.getenv("EMBEDDING_BINDING_HOST", "http://172.17.0.3:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_MODEL_API_KEY") or os.getenv(
    "EMBEDDING_BINDING_API_KEY", "api-key"
)
LLM_BINDING_API_KEY = LLM_API_KEY
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")

# 必须与你的 embedding 服务实际维度一致
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# rerank 配置
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "3"))
RERANK_ENDPOINT = os.getenv("RERANK_ENDPOINT", f"{BASE_URL}/rerank")
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "1234")
REQUEST_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "300"))

VLLM_BINDING_HOST = os.getenv("VLLM_BINDING_HOST", "qwen3.5-plus")
LLM_BINDING_HOST = os.getenv("LLM_BINDING_HOST", "qwen3.5-plus")
CHUNK_TOPK = int(os.getenv("CHUNK_TOPK", 20))
ENTITY_TOPK = int(os.getenv("ENTITY_TOPK", 3))
QUERY_MAX_ENTITY_TOKENS = int(os.getenv("QUERY_MAX_ENTITY_TOKENS", "600"))
QUERY_MAX_RELATION_TOKENS = int(os.getenv("QUERY_MAX_RELATION_TOKENS", "600"))
QUERY_MAX_TOTAL_TOKENS = int(os.getenv("QUERY_MAX_TOTAL_TOKENS", "2500"))
QUERY_LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", os.getenv("OPENAI_TIMEOUT", "300")))
QUERY_MAX_TOKENS = int(os.getenv("QUERY_MAX_TOKENS", "512"))
QUERY_TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))
QUERY_VLM_ENHANCED = os.getenv("QUERY_VLM_ENHANCED", "true").lower() == "true"
class Query(BaseModel):
    question: str = Field(..., min_length=1, max_length=20000)


def configure_logging():
    """Configure logging for the application."""
    log_dir = os.getenv("LOG_DIR", os.getcwd())
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.abspath(os.path.join(log_dir, datetime.now().strftime("rag_server_vllm_%H_%M_%d_%m_%Y.log")))

    log_max_bytes = int(os.getenv("LOG_MAX_BYTES", 10485760))
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", 5))

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(levelname)s: %(message)s",
                },
                "detailed": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                },
                "file": {
                    "formatter": "detailed",
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": log_file_path,
                    "maxBytes": log_max_bytes,
                    "backupCount": log_backup_count,
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                "lightrag": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "app": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
        }
    )

    logger.setLevel(logging.INFO)
    set_verbose_debug(os.getenv("VERBOSE", "false").lower() == "true")


app_logger = logging.getLogger("app")

# Query timing statistics
_query_times: list[float] = []
_total_queries = 0

async def qwen_rerank(
    query: str = None,
    documents: list[str] | None = None,
    docs: list[str] | None = None,
    top_n: int | None = None,
    **kwargs: Any,
) -> list[dict[str, float]]:
    """
    兼容 LightRAG 的 rerank 函数。

    返回格式严格对齐作者 generic_rerank_api:
    [
        {"index": int, "relevance_score": float},
        ...
    ]

    会自动忽略额外参数，例如：
    - max_tokens_per_doc
    - return_documents
    - enable_chunking
    """
    # 兼容不同调用方式
    top_n = RERANK_TOP_N
    input_docs = documents if documents is not None else docs
    print(f"QWEN_RERANKER = {top_n}")
    if not query or not input_docs:
        return []

    # LightRAG 可能会额外传这些参数，这里统一吞掉或复用
    max_tokens_per_doc = kwargs.pop("max_tokens_per_doc", None)
    _ = kwargs.pop("return_documents", None)
    _ = kwargs.pop("enable_chunking", None)
    _ = kwargs.pop("extra_body", None)

    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": input_docs,
    }

    if top_n is not None:
        payload["top_n"] = top_n

    headers = {
        "Authorization": f"Bearer {RERANK_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(
            RERANK_ENDPOINT,
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        response_json = resp.json()
    results = response_json.get("results", [])
    if not isinstance(results, list):
        results = []

    if not results:
        return []

    standardized_results = []
    for result in results:
        idx = result.get("index")
        score = result.get("relevance_score", 0.0)

        if isinstance(idx, int):
            standardized_results.append(
                {
                    "index": idx,
                    "relevance_score": float(score),
                }
            )
    return standardized_results


async def init_rag(
    output_dir: str,
    working_dir: Optional[str] = None,
    parser: Optional[str] = None,
):
    try:
        config = RAGAnythingConfig(
            working_dir=working_dir or "./rag_storage_unidocbench_27_file",
            parser=parser,
            parse_method="auto",
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
            max_context_tokens=500,
        )

        # 定义 LLM 模型函数
        def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
            history_messages = history_messages or []
            kwargs.pop("keyword_extraction", None)
            kwargs.setdefault("max_tokens", QUERY_MAX_TOKENS)
            kwargs.setdefault("temperature", QUERY_TEMPERATURE)
            return openai_complete_if_cache(
                LLM_MODEL,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=LLM_BINDING_API_KEY,
                base_url=LLM_BINDING_HOST,
                timeout=QUERY_LLM_TIMEOUT,
                # stream=True,
                **kwargs,
            )

        # 定义视觉模型函数用于图像处理
        def vision_model_func(
            prompt,
            system_prompt=None,
            history_messages=None,
            image_data=None,
            messages=None,
            **kwargs,
        ):
            history_messages = history_messages or []
            keyword_extraction = kwargs.pop("keyword_extraction", None)
            if keyword_extraction:
                kwargs["format"] = "json"
            # leng = len(kwargs["input_tokens"])
            # print(f"LENGH = {leng}")
            # 如果提供了 messages 格式（用于多模态增强查询），直接使用
            if messages:
                return openai_complete_if_cache(
                    VLLM_MODEL,
                    "",
                    system_prompt=None,
                    history_messages=[],
                    messages=messages,
                    api_key=VLLM_BINDING_API_KEY,
                    base_url=VLLM_BINDING_HOST,
                    **kwargs,
                )

            # 传统单图片格式
            elif image_data:
                msg_list = []
                if system_prompt:
                    msg_list.append({"role": "system", "content": str(system_prompt)})

                msg_list.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                },
                            },
                        ],
                    }
                )

                return openai_complete_if_cache(
                    VLLM_MODEL,
                    "",
                    system_prompt=None,
                    history_messages=[],
                    messages=msg_list,
                    api_key=VLLM_BINDING_API_KEY,
                    base_url=VLLM_BINDING_HOST,
                    **kwargs,
                )

            # 纯文本格式
            else:
                return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        embedding_func = EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            # send_dimensions=False,
            max_token_size=8192,
            func=lambda texts: openai_embed.func(
                texts,
                model=EMBEDDING_MODEL,
                api_key=EMBEDDING_API_KEY,
                base_url=EMBEDDING_BINDING_HOST,
            ),
        )
        rag = RAGAnything(
            config=config,
            llm_model_func=llm_model_func,
            vision_model_func=vision_model_func,
            embedding_func=embedding_func,
            lightrag_kwargs={
                "rerank_model_func": qwen_rerank,
                }
        )

        await rag._ensure_lightrag_initialized()
        return rag

    except Exception as e:
        app_logger.exception("Error processing with RAG: %s", str(e))
        raise
        
@asynccontextmanager
async def lifespan(app: FastAPI):
        # Startup: Initialize
        val = os.getenv("RAG_STORAGE", "./rag_storage")
        print(f"HERER : {val}")
        app.state.rag = await init_rag(
            os.getenv("OUTPUT_DIR", "./output"),
            os.getenv("RAG_STORAGE", "./rag_storage"),
            os.getenv("PARSER", "mineru"))
        app.state.rag_services = [await init_rag( os.getenv("OUTPUT_DIR", "./output"), os.getenv("RAG_STORAGE", "./rag_storage"), os.getenv("PARSER", "mineru")) for i in range(1)]
        app.state.service_pool = cycle(app.state.rag_services)
        yield
        app.state.rag = None
        app.state.rag_services = None


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/query")
async def query_endp(q: Query, request: Request):
    global _total_queries
    rag = next(app.state.service_pool)
    app_logger.info("Got query: %s", q.question)

    start_time = time.perf_counter()
    try:
        # res = await rag.lightrag.aquery(
        res = await rag.aquery(
            q.question,
            top_k=ENTITY_TOPK,
            chunk_top_k=CHUNK_TOPK,
            max_entity_tokens=QUERY_MAX_ENTITY_TOKENS,
            max_relation_tokens=QUERY_MAX_RELATION_TOKENS,
            max_total_tokens=QUERY_MAX_TOTAL_TOKENS,
            vlm_enhanced=QUERY_VLM_ENHANCED,
        )
        elapsed = time.perf_counter() - start_time
        _query_times.append(elapsed)
        _total_queries += 1
        avg_time = sum(_query_times) / len(_query_times)
        app_logger.info("Query completed in %.3fs (avg: %.3fs over %d queries)", elapsed, avg_time, _total_queries)
        return {"answer": res, "query_time_s": round(elapsed, 3), "avg_query_time_s": round(avg_time, 3), "total_queries": _total_queries}
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        app_logger.exception("Query failed after %.3fs", elapsed)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}") from e


def run_server():
    module_name = os.path.basename(__file__).split(".")[0]
    app_logger.info("Executing app: %s", module_name)
    uvicorn.run(
        f"{module_name}:app",
        host=os.getenv("RAG_IP", "127.0.0.1"),
        port=int(os.getenv("RAG_PORT", "8080")),
    )


def main():
    configure_logging()
    run_server()


if __name__ == "__main__":
    main()
