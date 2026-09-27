"""
vLLM Integration Example with RAG-Anything

This example demonstrates how to integrate vLLM with RAG-Anything for
high-throughput document processing and querying using locally or remotely
served models.

vLLM provides an OpenAI-compatible API server with continuous batching,
PagedAttention, and optimized inference — ideal for production RAG workloads.

Requirements:
- vLLM serving a model (see: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
- OpenAI Python package: pip install openai
- RAG-Anything installed: pip install raganything

Start vLLM (example):
    # Chat / completion model
    vllm serve Qwen/Qwen2.5-72B-Instruct --tensor-parallel-size 4

    # Embedding model (separate process, different port)
    vllm serve BAAI/bge-m3 --task embedding --port 8001

Environment Setup:
Create a .env file with:
LLM_BINDING=vllm
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct
LLM_BINDING_HOST=http://10.246.98.82:8000/v1
LLM_BINDING_API_KEY=token-abc123
EMBEDDING_BINDING=vllm
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_BINDING_HOST=http://10.246.98.82:8001/v1
EMBEDDING_BINDING_API_KEY=token-abc123
"""

import os
import uuid
import asyncio
from typing import List, Dict, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI
import logging
import logging.config
from pathlib import Path
import json
from collections import Counter
# Load environment variables
import time
# RAG-Anything imports
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc, logger, set_verbose_debug
from lightrag.llm.openai import openai_complete_if_cache
from typing import Optional, List, Dict

dotenv_file = os.getenv('DOTENV_FILE', '.env')

load_dotenv(dotenv_path=dotenv_file, override=True)

# Benchmark results directory
BENCHMARK_NAME = os.getenv("BENCHMARK_NAME", "bench_output")
BENCHMARK_RESULTS_DIR = f"{BENCHMARK_NAME}_results"

# vLLM configuration from environment variables
LLM_BASE_URL = os.getenv("LLM_BINDING_HOST", "http://10.246.98.82:8000/v1")
LLM_MODEL_NAME = os.getenv("LLM_MODEL", "Qwen2.5-7B-Instruct")
LLM_API_KEY = os.getenv("LLM_MODEL_API_KEY", "token-abc123")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL", "Qwen3/Qwen3-VL-8B-Instruct")
VLLM_BASE_URL = os.getenv("VLLM_BINDING_HOST", "http://10.246.98.82:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_MODEL_API_KEY", "dummy")

LLM_EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
LLM_EMBED_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST", "http://10.246.98.82:8001/v1")
LLM_EMBED_API_KEY = os.getenv("EMBEDDING_MODEL_API_KEY", "token-abc123")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
EMBEDDING_SEND_DIM = os.getenv("EMBEDDING_SEND_DIM", "false").lower() == "true"
max_concurrent_files = os.getenv("MAX_CONCURRENT_FILES", 1)
workers = int(os.getenv("WORKERS", 2))
doc_file_path = os.getenv("DOC_FILE_PATH", "/home/RAG-Anything/UniDoc-Bench/test_stucked_files")

def configure_logging():
    """Configure logging for the application"""
    # Get log directory path from environment variable or use current directory
    log_dir = os.getenv("LOG_DIR", os.getcwd())
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = os.path.abspath(os.path.join(log_dir, f"raganything_vllm_unidocbench_{timestamp}.log"))

    os.makedirs(os.path.dirname(log_dir), exist_ok=True)

    # Get log file max size and backup count from environment variables
    log_max_bytes = int(os.getenv("LOG_MAX_BYTES", 10485760))  # Default 10MB
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", 5))  # Default 5 backups

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
                    },
                }
            )

    # Set the logger level to INFO
    logger.setLevel(logging.INFO)
    # Enable verbose debug if needed
    set_verbose_debug(os.getenv("VERBOSE", "false").lower() == "true")

# app_logger = logging.getLogger("build_npu")

async def llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function for LightRAG (pickle-safe).

    Uses openai_complete_if_cache since vLLM exposes an OpenAI-compatible API.
    """
    return await openai_complete_if_cache(
        model=LLM_MODEL_NAME,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=1200,
        **kwargs,
    )

async def vision_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    image_data: Optional[str] = None,
    **kwargs,
) -> str:
    """Top-level VLM function for LightRAG.

    If image_data is provided, send a multimodal request to the vLLM
    OpenAI-compatible server. Otherwise, fall back to the normal text LLM.
    """
    history_messages = history_messages or []

    if image_data:
        messages = [
            {"role": "system", "content": system_prompt} if system_prompt else None,
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
            },
        ]

        # 过滤掉 None
        messages = [m for m in messages if m is not None]

        return await openai_complete_if_cache(
            model=VLLM_MODEL_NAME,
            prompt="",
            system_prompt=None,
            history_messages=[],
            messages=messages,
            api_key=VLLM_API_KEY,
            base_url=VLLM_BASE_URL,
            timeout=1200,
            **kwargs,
        )
    else:
        return await llm_model_func(
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            timeout=1200,
            **kwargs,
        )


async def vllm_embedding_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function for LightRAG (pickle-safe).

    Connects to vLLM's embedding endpoint (may run on a separate port).
    """
    from lightrag.llm.openai import openai_embed

    embeddings = await openai_embed.func(
        texts=texts,
        model=LLM_EMBED_MODEL,
        base_url=LLM_EMBED_BASE_URL,
        api_key=LLM_EMBED_API_KEY,
    )
    return embeddings


class VLLMRAGIntegration:
    """Integration class for vLLM with RAG-Anything."""

    def __init__(self):
        # vLLM configuration using standard LLM_BINDING variables
        self.base_url = os.getenv("VLLM_BINDING_HOST", "http://10.246.98.82:22000/v1")
        self.api_key = os.getenv("VLLM_BINDING_API_KEY", "token-abc123")
        self.model_name = os.getenv("VLLM_MODEL", "Qwen3/Qwen3-VL-8B-Instruct")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.embedding_base_url = os.getenv(
            "EMBEDDING_BINDING_HOST", "http://10.246.98.82:8800/v1"
        )
        self.embedding_api_key = os.getenv("EMBEDDING_BINDING_API_KEY", "token-abc123")

        # RAG-Anything configuration
        # Use a fresh working directory each run to avoid legacy doc_status schema conflicts
        self.config = RAGAnythingConfig(
            working_dir=os.getenv("RAG_STORAGE", "./rag_storage_vllm"), # "./rag_storage_vllm",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
            max_concurrent_files=max_concurrent_files,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")

        self.rag = None

    def _build_processed_file_set(self) -> set:
        """Build a set of processed file_path values from kv_store_doc_status.json."""
        processed_files = set()
        try:
            status_file = Path(self.config.working_dir) / "kv_store_doc_status.json"
            if not status_file.exists():
                print(f"⚠️ Status file not found: {status_file}")
                return processed_files

            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                print(f"⚠️ Invalid status file format: {status_file}")
                return processed_files

            for _, item in data.items():
                if not isinstance(item, dict):
                    continue
                if item.get("status") == "processed" and item.get("file_path"):
                    processed_files.add(item["file_path"])

            return processed_files

        except Exception as e:
            print(f"⚠️ Failed to load processed file set: {e}")
            return processed_files

    def embedding_func_factory(self):
        """Create a completely serializable embedding function."""
        return EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,  # bge-m3 context length
            send_dimensions=EMBEDDING_SEND_DIM,
            model_name=LLM_EMBED_MODEL,
            func=vllm_embedding_async,
        )

    async def initialize_rag(self):
        """Initialize RAG-Anything with vLLM functions."""
        print("Initializing RAG-Anything with vLLM...")

        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=llm_model_func,
                vision_model_func=vision_model_func,
                embedding_func=self.embedding_func_factory(),
            )

            # Compatibility: avoid writing unknown field 'multimodal_processed' to LightRAG doc_status
            async def _noop_mark_multimodal(doc_id: str):
                return None

            self.rag._mark_multimodal_processing_complete = _noop_mark_multimodal

            print("✅ RAG-Anything initialized successfully!")
            return True
        except Exception as e:
            print(f"❌ RAG initialization failed: {str(e)}")
            return False

    async def insert_content_list_debug_v1(self, path):
        if not self.rag:
            print("❌ RAG not initialized")
            return

        try:
            path = Path(path)
            json_files = sorted(path.rglob("*_content_list.json"))
            print(json_files)
            if not json_files:
                print(f"⚠️ No *_content_list.json files found under: {path}")
                return

            processed_file_set = self._build_processed_file_set()

            total_files = len(json_files)
            success_count = 0
            fail_count = 0
            skipped_count = 0
            total_start = time.time()

            global_type_counter = Counter()
            global_item_count = 0

            print(f"\n📥 Insert content list started")
            print(f"📁 Root path       : {path}")
            print(f"📄 Total json files: {total_files}")
            print(f"✅ Already processed files in status store: {len(processed_file_set)}\n")

            for idx, json_file in enumerate(json_files, start=1):
                file_start = time.time()
                print("=" * 80)
                print(f"🔄 Processing [{idx}/{total_files}]")
                print(f"📄 File: {json_file.name}")

                try:
                    file_ref = json_file.stem.replace("_content_list", "")
                    pdf_file_name = f"{file_ref}.pdf"

                    if pdf_file_name in processed_file_set:
                        skipped_count += 1
                        elapsed = time.time() - file_start
                        print(f"⏭️ Skipped [{idx}/{total_files}] {json_file.name}")
                        print(f"📌 Reason: already processed")
                        print(f"📄 file_path: {pdf_file_name}")
                        print(f"⏱️ File time: {elapsed:.2f}s")
                        continue

                    with open(json_file, "r", encoding="utf-8") as f:
                        content_list = json.load(f)

                    type_counter = Counter(item.get("type", "UNKNOWN") for item in content_list)

                    num_items = len(content_list)
                    global_type_counter.update(type_counter)
                    global_item_count += num_items

                    print(f"🧩 Content items: {num_items}")
                    print("📊 Type distribution:")
                    for t, c in type_counter.items():
                        print(f"   - {t:<12}: {c}")

                    await self.rag.insert_content_list(
                        content_list=content_list,
                        file_path=pdf_file_name,
                        display_stats=True,
                    )

                    elapsed = time.time() - file_start
                    success_count += 1
                    print(f"✅ Done [{idx}/{total_files}] {json_file.name}")
                    print(f"📄 file_path: {pdf_file_name}")
                    print(f"⏱️ File time: {elapsed:.2f}s")

                except Exception as e:
                    elapsed = time.time() - file_start
                    fail_count += 1
                    print(f"❌ Failed [{idx}/{total_files}] {json_file.name}")
                    print(f"⏱️ File time: {elapsed:.2f}s")
                    print(f"Error: {e}")

            total_elapsed = time.time() - total_start

            print("\n" + "=" * 80)
            print("📊 Insert content list summary123")
            print(f"Total files : {total_files}")
            print(f"Success     : {success_count}")
            print(f"Skipped     : {skipped_count}")
            print(f"Failed      : {fail_count}")
            print(f"Total items : {global_item_count}")
            print(f"Total time  : {total_elapsed:.2f}s")
            if total_files > 0:
                print(f"Avg/file    : {total_elapsed / total_files:.2f}s")

            print("\n📊 Global type distribution:")
            for t, c in global_type_counter.items():
                ratio = c / global_item_count if global_item_count > 0 else 0
                print(f"   - {t:<12}: {c} ({ratio:.2%})")

            print("=" * 80)

        except Exception as e:
            print(f"❌ Insert content failed: {str(e)}")


async def main():
    """Main example function."""
    print("=" * 70)
    print("vLLM + RAG-Anything Integration Example")
    print("=" * 70)
    # 日志
    configure_logging()

    # Track build time
    build_start_time = time.time()

    # Initialize integration
    integration = VLLMRAGIntegration()

    # Initialize RAG
    if not await integration.initialize_rag():
        return False

    # insert content list
    await integration.insert_content_list_debug_v1(path=doc_file_path)

    # Calculate and save build time
    build_time = time.time() - build_start_time

    # Ensure results directory exists
    os.makedirs(BENCHMARK_RESULTS_DIR, exist_ok=True)

    # Save or update timings.json
    timings_file = os.path.join(BENCHMARK_RESULTS_DIR, "timings.json")
    timings = {}
    if os.path.exists(timings_file):
        with open(timings_file, "r") as f:
            timings = json.load(f)

    timings["build_time"] = round(build_time, 2)

    with open(timings_file, "w") as f:
        json.dump(timings, f, indent=2)

    print(f"\n⏱️ Total build time: {build_time:.2f}s")
    print(f"📝 Build time saved to: {timings_file}")

    return True


if __name__ == "__main__":
    print("🚀 Starting vLLM integration")
    success = asyncio.run(main())

    exit(0 if success else 1)
