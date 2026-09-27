"""HTTP adapters for the three competition-specified models; no alternative models."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    parsed_root: str = "../mineru-parsed"
    pdf_root: str = "../original_pdf_files_100"
    index_dir: str = "artifacts/index"
    legacy_storage: str = "../索引与demo代码-0730/RAG-Anything-0713/RAG_STORAGE_0713_retry"
    llm_url: str = "http://127.0.0.1:8100/v1/chat/completions"
    llm_model: str = "Qwen3-VL-8B-Instruct"
    embedding_url: str = "http://127.0.0.1:8001/v1/embeddings"
    embedding_model: str = "bge-m3"
    rerank_url: str = "http://127.0.0.1:8002/v1/rerank"
    rerank_model: str = "bge-reranker-v2-m3"
    embedding_dim: int = 1024
    max_rounds: int = 3
    candidates: int = 60
    evidence_blocks: int = 12
    max_images: int = 6
    context_chars: int = 24000
    request_timeout: float = 90
    query_deadline: float = 240
    max_output_tokens: int = 1200
    use_vector: bool = True
    use_graph: bool = True
    use_rerank: bool = True
    use_planner: bool = True
    use_vision: bool = True

    @classmethod
    def load(cls, file):
        path = Path(file).resolve()
        data = json.loads(path.read_text("utf-8"))
        unknown = set(data)-{f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown config fields: {sorted(unknown)}")
        cfg = cls(**data)
        for attr in ("parsed_root", "pdf_root", "index_dir", "legacy_storage"):
            value = getattr(cfg, attr)
            setattr(cfg, attr, str((path.parent / value).resolve()))
        for name in ("max_rounds", "candidates", "evidence_blocks", "max_images", "context_chars", "embedding_dim"):
            if getattr(cfg, name) < 1:
                raise ValueError(f"{name} must be positive")
        if cfg.max_rounds > 5 or cfg.request_timeout <= 0 or cfg.query_deadline <= 0:
            raise ValueError("Invalid time/round budget")
        return cfg


class ModelError(RuntimeError):
    pass


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ModelError("Model did not return a valid JSON object") from exc
    if not isinstance(value, dict):
        raise ModelError("Expected a JSON object")
    return value


class Models:
    def __init__(self, config, deadline=None):
        self.cfg = config
        self.deadline = deadline
        self.calls = []

    def post(self, url, payload, service):
        remaining = self.cfg.query_deadline if self.deadline is None else self.deadline-time.monotonic()
        if remaining <= 0:
            raise ModelError("Query deadline exceeded")
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(f"RAG_{service.upper()}_API_KEY", "")
        if key:
            headers["Authorization"] = "Bearer " + key
        request = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=min(self.cfg.request_timeout, remaining)) as response:
                value = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # Do not log Authorization headers or response body, which can contain secrets.
            raise ModelError(f"{service} request failed ({type(exc).__name__})") from exc
        self.calls.append({"service": service, "seconds": round(time.perf_counter()-started, 4),
                           "usage": value.get("usage", {})})
        return value

    def chat(self, system, content, max_tokens=None):
        value = self.post(self.cfg.llm_url, {"model": self.cfg.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0, "max_tokens": max_tokens or self.cfg.max_output_tokens}, "llm")
        try:
            choice = value["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("Model output was truncated")
            return parse_json(choice["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Invalid chat response") from exc

    def embed(self, texts):
        import numpy as np
        response = self.post(self.cfg.embedding_url,
            {"model": self.cfg.embedding_model, "input": texts}, "embedding")
        try:
            rows = sorted(response["data"], key=lambda x: x["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError("Embedding indices missing or duplicated")
            vectors = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
            if vectors.shape != (len(texts), self.cfg.embedding_dim) or not np.isfinite(vectors).all():
                raise ValueError("Invalid embedding shape or values")
            if (np.linalg.norm(vectors, axis=1) == 0).any():
                raise ValueError("Zero embedding")
            return vectors
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError("Invalid embedding response") from exc

    def rerank(self, question, texts):
        response = self.post(self.cfg.rerank_url, {"model": self.cfg.rerank_model,
            "query": question, "documents": texts, "top_n": len(texts)}, "rerank")
        try:
            items = response["results"]
            indices = [x["index"] for x in items]
            if sorted(indices) != list(range(len(texts))):
                raise ValueError("Rerank result must be a permutation")
            return indices
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError("Invalid rerank response") from exc
