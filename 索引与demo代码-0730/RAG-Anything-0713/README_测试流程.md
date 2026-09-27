# RAG-Anything-0713 测试过程


## 0. 文件名恢复（运行测试前先执行）

当前目录中部分关键文件已改成普通文件名，避免出现点开头文件或无后缀文件：

| 当前文件 | 恢复后的项目默认文件 |
| --- | --- |
| `env.runtime.txt` | `.env` |
| `pre-commit-config.yaml` | `.pre-commit-config.yaml` |
| `LICENSE.txt` | `LICENSE` |
| `rag-anything-experiments/env.experiments.txt` | `rag-anything-experiments/.env` |
| `raganything.egg-info/PKG-INFO.txt` | `raganything.egg-info/PKG-INFO` |

运行测试前先执行：

```bash
python scripts/restore_original_filenames.py
```


## 1. 目录与环境


| 项目 | 路径 |
| --- | --- |
| 运行配置 | `.env` (注：`将env.example`重命名成`.env`即可)|
| 30 条测试问题 | `queries_30.json` |
| MinerU 解析数据 | `mineru-parsed` |
| 索引目录 | `RAG_STORAGE_0713_retry` |
| 历史测试结果 | `TEST_bench_output_results` |


## 2. 启动 vLLM 模型服务

使用 4 张 NVIDIA A800 80GB：GPU 0、1 部署 Qwen3-VL，GPU 2 部署 Embedding，GPU 3 部署 Reranker。

### 2.1 Qwen3-VL

```bash
CUDA_VISIBLE_DEVICES=0,1 vllm serve \
 /path/to/your/Qwen3-VL-8B-Instruct \
  --host 127.0.0.1 \
  --port 8100 \
  --served-model-name /path/to/your/Qwen3-VL-8B-Instruct \
  --trust-remote-code \
  --tensor-parallel-size 2 \
  --gpu-memory-utilization 0.85 \
  --max-model-len 50000 \
  --max-num-seqs 4
```


### 2.2 bge-m3 Embedding


```bash
CUDA_VISIBLE_DEVICES=2 vllm serve \
 /path/to/your/bge-m3 \
  --host 127.0.0.1 \
  --port 8001 \
  --served-model-name /path/to/your/bge-m3 \
  --trust-remote-code \
  --gpu-memory-utilization 0.45 \
  --max-model-len 50000
```


### 2.3 bge-reranker-v2-m3


```bash
CUDA_VISIBLE_DEVICES=3 vllm serve \
 /path/to/your/bge-reranker-v2-m3 \
  --host 127.0.0.1 \
  --port 8002 \
  --served-model-name /path/to/your/bge-reranker-v2-m3 \
  --trust-remote-code \
  --gpu-memory-utilization 0.45 \
  --max-model-len 50000
```


## 3. 配置测试参数

使用 `.env`。关键配置如下：

```dotenv
LLM_BINDING_HOST=http://127.0.0.1:8100/v1
LLM_MODEL=/path/to/your/Qwen3-VL-8B-Instruct
VLLM_BINDING_HOST=http://127.0.0.1:8100/v1
VLLM_MODEL=/path/to/your/Qwen3-VL-8B-Instruct

EMBEDDING_BINDING_HOST=http://127.0.0.1:8001/v1
EMBEDDING_MODEL=/path/to/your/bge-m3
EMBEDDING_DIM=1024

RERANK_ENDPOINT=http://127.0.0.1:8002/v1/rerank
RERANK_MODEL=/path/to/your/bge-reranker-v2-m3
RERANK_TOP_N=10
```

数据及输出配置：

```dotenv
BENCHMARK_NAME=UNIDOCBENCH_0713_retry
BENCH_QUERIES=queries_30.json
DOC_FILE_PATH=mineru-parsed
RAG_STORAGE=RAG_STORAGE_0713_retry
RAG_BINDING_HOST=http://127.0.0.1:8080/query
LOG_DIR=./all_logs
```

索引和查询配置：

```dotenv
QUERY_MODE=mix
CHUNK_SIZE=300
CHUNK_OVERLAP_SIZE=15
CHUNK_TOPK=40
ENTITY_TOPK=30
RERANK_TOP_N=10

QUERY_MAX_ENTITY_TOKENS=600
QUERY_MAX_RELATION_TOKENS=600
QUERY_MAX_TOTAL_TOKENS=2500
QUERY_MAX_TOKENS=512
QUERY_VLM_ENHANCED=true

MAX_CONCURRENT_FILES=1
WORKERS=1
MAX_ASYNC=1
LLM_TIMEOUT=1200
MAX_TOKENS=1024
TEMPERATURE=0
```

## 4. 构建索引


```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build
```



## 5. 启动索引查询服务


```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server
```


## 6. 运行测试


```bash
DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag
```


按当前 `.env`，结果目录为：

```text
UNIDOCBENCH_0713_retry_results/
```

主要结果文件：

| 文件 | 内容 |
| --- | --- |
| `rag_answers.json` | 原始 RAG 回答 |
| `rag_answers_judged.json` | 每题预测、得分和评判理由 |
| `rag_answers_judged_summary.json` | 总体、领域和答案类型汇总 |
| `timings.json` | 索引构建和查询总耗时 |
