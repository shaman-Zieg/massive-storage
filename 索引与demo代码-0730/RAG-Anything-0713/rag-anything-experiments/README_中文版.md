# RAG-Anything 实验代码使用说明

本文档介绍如何准备运行环境、构建索引、启动检索服务，以及运行 UniDocBench100 基准测试。

---

## 1. 环境准备

### 1.1 安装 `uv`

本项目使用 `uv` 管理 Python 环境和依赖，请提前安装 `uv`。

---

### 1.2 获取 RAG-Anything

克隆官方仓库：

```bash
git clone https://github.com/HKUDS/RAG-Anything.git
```

进入项目目录：

```bash
cd RAG-Anything
```

切换到指定版本：

```bash
git checkout v1.2.9
```

当前实验环境使用：

```text
RAG-Anything: v1.2.9
LightRAG:     v1.4.9.11
```

---

### 1.3 获取实验代码

将当前实验仓库克隆或复制到 `RAG-Anything` 项目中。

例如，最终目录结构可参考：

```text
RAG-Anything/
├── rag-anything-experiments/
├── .env
└── all_logs
└── mineru-parsed
└── queries_100.json
```

其中：

```text
rag-anything-experiments/
```

为当前实验代码目录。

---

## 2. 准备 MinerU 解析结果

实验需要 MinerU 生成的文档解析结果，即包含 `content_list` 等文件的输出目录。

有两种方式。

### 方式一：直接使用已有 MinerU 输出

将已经生成好的 MinerU 解析目录复制到实验目录附近，并在 `.env` 中正确配置：

```text
DOC_FILE_PATH
```

---

### 方式二：使用脚本调用 MinerU 解析

首先在 `.env` 中配置 PDF 路径和输出目录，然后执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh parse_docs
```

当前 MinerU 解析默认使用本地计算资源，不依赖外部推理服务。

---

## 3. 单文件端到端测试

运行测试前，请先在配置文件中设置正确的 LLM、VLM、Embedding 等服务 IP、端口和模型名称。

执行：

```bash
bash rag-anything-experiments/run_e2e.sh
```

测试所使用的主要参数配置在：

```text
.env
```

---

# 4. 检索流程

`DOTENV_FILE` 用于指定实验配置文件。

例如：

```bash
DOTENV_FILE=.env ...
```

表示使用当前目录下的 `.env` 配置启动实验。

---

## 4.1 启动 RAG 检索服务

执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server
```

该命令会启动一个简单的 HTTP 服务。

服务接收用户 Query，并调用 RAG 系统执行检索。

---

## 4.2 发送 Benchmark Query

启动检索服务后，在另一个终端执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag
```

该命令会读取 Benchmark Query，并发送到步骤 4.1 启动的 RAG Server。

---

### 说明

严格来说，RAG Server 并不是 Benchmark 必需组件。

当前设计主要用于：

```text
Benchmark Client
        ↓ HTTP
RAG Server
        ↓
RAG System
```

通过 HTTP Server 解耦：

* Benchmark 测试逻辑
* RAG 系统执行逻辑

---

# 5. 索引构建

执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build
```

索引构建完成后，索引数据会保存到 `.env` 中配置的：

```text
RAG_STORAGE
```

目录。

---

# 6. UniDocBench100 分阶段配置说明

完整流程分为三个阶段：

```text
PDF Parsing
    ↓
Index Build
    ↓
Search & Evaluation
```

---

## 6.1 阶段一：文档解析

主要环境变量如下。

### `DOCS_PATH`

待 MinerU 解析的原始文档路径。

```text
DOCS_PATH=/path/to/pdf/files
```

---

### `PARSER_OUTPUT_DIR`

MinerU 解析结果输出目录。

该目录将保存 `content_list` 等解析结果。

```text
PARSER_OUTPUT_DIR=/path/to/mineru/output
```

---

### `MINERU_VLM`

控制 MinerU 使用的解析后端。

```text
MINERU_VLM=true
```

表示使用 VLM Backend。

```text
MINERU_VLM=false
```

表示使用 Pipeline Backend。

更详细的参数说明请参考 MinerU 官方帮助信息。

当前实验中，MinerU 使用本地计算资源完成解析，不调用外部服务。

---

## 6.2 阶段二：索引构建

主要环境变量如下。

### `RAG_STORAGE`

RAG 索引保存路径。

```text
RAG_STORAGE=/path/to/rag/storage
```

---

### `DOC_FILE_PATH`

MinerU `content_list` 文件所在目录。

```text
DOC_FILE_PATH=/path/to/content_lists
```

---

### `LLM_BINDING_HOST`

LLM 服务地址。

```text
LLM_BINDING_HOST=http://<ip>:<port>
```

---

### `LLM_MODEL`

LLM 服务部署的模型名称。

```text
LLM_MODEL=<model_name>
```

---

### `VLLM_BINDING_HOST`

视觉语言模型服务地址。

```text
VLLM_BINDING_HOST=http://<ip>:<port>
```

---

### `VLLM_MODEL`

视觉语言模型名称。

```text
VLLM_MODEL=<visual_model_name>
```

---

### `EMBEDDING_MODEL`

Embedding 模型名称。

```text
EMBEDDING_MODEL=<embedding_model_name>
```

---

### `EMBEDDING_BINDING_HOST`

Embedding 服务地址。

```text
EMBEDDING_BINDING_HOST=http://<ip>:<port>
```

---

## 6.3 阶段三：检索与评测

主要环境变量如下。

### `RAG_STORAGE`

已经构建完成的 RAG 索引目录。

```text
RAG_STORAGE=/path/to/rag/storage
```

---

### `BENCH_QUERIES`

Benchmark Query JSON 文件路径。

```text
BENCH_QUERIES=/path/to/queries_100.json
```

---

### `JUDGER_BINDING_HOST`

Judger 模型 API 地址。

```text
JUDGER_BINDING_HOST=http://<ip>:<port>
```

---

### `JUDGER_MODEL`

Judger 模型名称。

```text
JUDGER_MODEL=<judger_model_name>
```

---

### `JUDGER_API_KEY`

Judger API Key。

```text
JUDGER_API_KEY=<your_api_key>
```

---

### `RERANK_MODEL`

Rerank 模型名称。

```text
RERANK_MODEL=<rerank_model_name>
```

---

### `RERANK_ENDPOINT`

Rerank 服务地址。

```text
RERANK_ENDPOINT=http://<ip>:<port>
```

---

### `RERANK_API_KEY`

Rerank 服务 API Key。

```text
RERANK_API_KEY=<your_api_key>
```

---

### `RAG_BINDING_HOST`

本地 RAG Server 地址。

```text
RAG_BINDING_HOST=http://<ip>:<port>
```

如果端口已经被占用，请修改为其他可用端口。

---

### `BENCHMARK_NAME`

Benchmark 名称。

中间结果和最终结果目录会使用该名称作为前缀。

```text
BENCHMARK_NAME=unidocbench100
```

---

# 7. UniDocBench100 快速开始

## 7.1 准备代码

首先完成前文：

```text
1. 环境准备
2. 获取 RAG-Anything
3. 准备 rag-anything-experiments
```

---

## 7.2 准备目录结构

进入 `rag-anything-experiments` 的父目录。

推荐目录结构如下：

```text
workspace/
├── .env
├── rag-anything-experiments/
├── mineru-parsed/
├── queries_100.json
└── all_logs/
```

其中：

```text
.env
```

为实验配置文件。

---

### 文档输入方式一：使用已有 MinerU 结果 （已提供，建议使用）

将 MinerU 解析后的目录放在 `.env` 附近，例如：

```text
workspace/
├── .env
├── mineru-parsed/
└── rag-anything-experiments/
```

然后设置：

```text
DOC_FILE_PATH=/path/to/mineru-parsed
```

---

### 文档输入方式二：从原始 PDF 开始

将原始 PDF 文件放在 `.env` 附近，例如：

```text
workspace/
├── .env
├── original_pdf_files_100/
└── rag-anything-experiments/
```

然后通过 MinerU 解析。

---

### 准备 Query 文件

将：

```text
queries_100.json
```

放在 `.env` 附近。

例如：

```text
workspace/
├── .env
├── queries_100.json
└── rag-anything-experiments/
```

---

## 7.3 配置 API Key

请基于提供的模型在本地环境进行部署（建议用vLLM），在 `.env` 中配置以下参数：
*注意：我们已提供目标模型，为保证比赛公平性，请不要改变使用的模型*

```bash
JUDGER_API_KEY=<your_api_key>

VLLM_MODEL_API_KEY=<your_api_key>

LLM_MODEL_API_KEY=<your_api_key>

EMBEDDING_MODEL_API_KEY=<your_api_key>

RERANK_API_KEY=<your_api_key>
```

---

## 7.4 配置 MinerU 解析结果路径

设置：

```bash
DOC_FILE_PATH=/path/to/content_lists
```

该路径应指向包含 MinerU `content_list` 文件的目录。

---

## 7.5 配置最终分数参数

最终 Score 使用两个系数：

```bash
COEFFICIENT_A=1.0
COEFFICIENT_B=5.0
```

其中：

```text
COEFFICIENT_A
```

对应公式中的 `alpha`，默认值：

```text
1.0
```

```text
COEFFICIENT_B
```

对应公式中的 `beta`，默认值：

```text
5.0
```

---

## 7.6 创建日志目录

在 `rag-anything-experiments` 的父目录创建：

```bash
mkdir -p all_logs
```

---

## 7.7 处理 Embedding Dimension 不匹配问题

当前版本中，如果使用：

```text
bge-m3
```

其 Embedding Dimension 为：

```text
1024
```

但 LightRAG 某些代码可能默认使用：

```text
1536
```

因此需要修改：

```text
.venv/lib/python3.12/site-packages/lightrag/llm/openai.py
```

将：

```python
embedding_dim=1536
```

修改为：

```python
embedding_dim=1024
```

如果文件中存在多处：

```python
embedding_dim=1536
```

需要全部修改。

> 注意：该修改仅适用于当前使用 1024 维 Embedding 模型的情况，例如 `bge-m3`。如果更换 Embedding 模型，请根据实际输出维度进行配置。

---

# 8. UniDocBench100 完整运行流程

## Step 1：解析 PDF

如果已经存在 MinerU 解析结果，可以跳过该步骤。

执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh parse_docs
```

---

## Step 2：构建索引

执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build
```

索引将保存到：

```text
RAG_STORAGE
```

指定的目录。

---

## Step 3：启动 RAG Server

执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server
```

保持该终端运行。

---

## Step 4：发送 Benchmark Query

打开另一个终端，执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag
```

Benchmark Client 将向 RAG Server 发送 Query，并完成：

```text
Query
  ↓
Retrieval
  ↓
Answer Generation
  ↓
Judging
  ↓
Score Calculation
```

---

# 9. Benchmark 结果

实验完成后，检查目录：

```text
unidocbench100_results/
```

主要文件如下。

---

## 9.1 `rag_answers_judged_summary.json`

包含所有 Query 的整体 Accuracy 汇总结果。

```text
rag_answers_judged_summary.json
```

主要用于查看：

* 总体正确率
* Query 评测结果汇总

---

## 9.2 `timings.json`

包含索引构建和检索耗时。

```text
timings.json
```

主要包括：

* Build Time
* Search Time

---

## 9.3 `final_scores.json`

包含最终 Benchmark Score。

最终分数计算公式为：

```text
Final Score
=
Accuracy
-
alpha × (Actual Search Time - Baseline Search Time) / Baseline Search Time
-
beta × (Actual Build Time - Baseline Build Time) / Baseline Build Time
```

其中：

```text
alpha = COEFFICIENT_A
beta  = COEFFICIENT_B
```

默认值：

```text
alpha = 1.0
beta  = 5.0
```

因此默认公式为：

```text
Final Score
=
Accuracy
-
1.0 × (Actual Search Time - Baseline Search Time) / Baseline Search Time
-
5.0 × (Actual Build Time - Baseline Build Time) / Baseline Build Time
```

---

# 10. 最简运行流程

如果环境、MinerU 结果和 `.env` 均已准备完成，只需要依次执行：

### 1. 构建索引

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build
```

### 2. 启动 RAG Server

```bash
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server
```

### 3. 启动 Benchmark

在另一个终端执行：

```bash
DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag
```

最终查看：

```text
unidocbench100_results/
```
