## How to use current code:

- install uv tool to run 
- ```git clone https://github.com/HKUDS/RAG-Anything.git```
- Switch to v1.2.9
- For lightrag was used v1.4.9.11
- ```cd RAG-Anything```
- git clone or copy current repo.
- copy minerU output folder(folder with content lists files) if you have, if not, then prepare it using minerU.
- you can also use prepared script for minerU parsing:
    ```DOTENV_FILE=.env bash rag-anything-experiments/run.sh parse_docs```
- full e2e test with single file can be started with, before testing set correct ip and port for LLM services:
    ```bash rag-anything-experiments/run_e2e.sh```

**Parameters with which tests were executed see in ".env" file**


# How to
## How to start retrieval:
<ins>DOTENV_FILE - contains parameters with which benchmarking will be started</ins>

**1. Start server:**
This command will start a simple http server that will get user query and start retrieval.


```DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server```


**2. Start sending benchmark queries:**
This command will start to send queries to the server started in step 1.

```DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag```

Notes: Actually server at step 1 is not really needed, it's just a way to unbound rag-system and benchmark.

## How to start index build:


```DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build```

# Step by step details for Unidocbench100
1. Docs parsing environment variables:

```DOCS_PATH - path to your documents that will be parsed by mineru```

```PARSER_OUTPUT_DIR - output path that will contain content lists```

```MINERU_VLM - if true vlm backend, false - pipeline, for details: see minerU help```

Currently for parsing, mineru uses local resources, not external services.

2. Index build stage environment variable

```RAG_STORAGE - path where index will be stored```

```DOC_FILE_PATH - path to content lists```

```LLM_BINDING_HOST - host where llm is located```

```LLM_MODEL - llm model name deployed at host```

```VLLM_BINDING_HOST - visual model host address```

```VLLM_MODEL - name of a visual model```

```EMBEDDING_MODEL - name of embedding model```

```EMBEDDING_BINDING_HOST - host of the embedding model```

3. Search stage

```RAG_STORAGE - path to rag-anything storage, where build index is stored```

```BENCH_QUERIES - path to json with queries```

```JUDGER_BINDING_HOST - host for judger api ```

```JUDGER_MODEL - name of the judger model ```

```JUDGER_API_KEY - api key of a judger model```

```RERANK_MODEL - rerank model name```

```RERANK_ENDPOINT - host of the rerank model```

```RERANK_API_KEY - api key for rerank```

```RAG_BINDING_HOST - address for local server, if current port is already allocated change it```

```BENCHMARK_NAME - intermediate results of benchmark will be put in folder with this prefix```

## Unidocbench100 quick start
- Before start you should prepare all code base(see: 'How to use current code') 

- Go to parent folder of rag-anything-experiments

  - Put **.env** to parent folder of rag-anything-experiments

  - Extract and place mineru-parsed folder next to .env .
    Or original_pdf_files_100 files also next to .env

  - Place queries_100.json next to .env
  - For current problem with dimension mismatch: in file: .venv/lib/python3.12/site-packages/lightrag/llm/openai.py change all: embedding_dim=1536 to embedding_dim=1024(if you use bge-m3)

Change following parameters:

```JUDGER_API_KEY=``` set your api-key

```VLLM_MODEL_API_KEY=``` set your api-key

```LLM_MODEL_API_KEY=``` set your api-key

```EMBEDDING_MODEL_API_KEY=``` set your api-key

```RERANK_API_KEY=``` set your api-key

```DOC_FILE_PATH=``` set path to folder with your content lists

```COEFFICIENT_A=1.0``` alpha for calculation of final score, by default: 1

```COEFFICIENT_B=5.0``` beta for calculation of final score, by default: 5

- In parent folder of rag-anything-experiments create folder all_logs.

- Parse pdfs with minerU (you can skip step, if it already generated).

```DOTENV_FILE=.env bash rag-anything-experiments/run.sh parse_docs```

- Build index:

```DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build```

- Then start server:

```DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server```

- Start sending queries:

```DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag```

- After completion check folder *unidocbench100_results*:

 rag_answers_judged_summary.json - accuracy summary over all queries

 timings.json - contains build and search time.

 final_scores.json - contains results according to formula: 

 ```final score  = Accuracy - alpha * (actual search time - baseline search time)/baseline - beta * (actual build time - baseline build time)/baseline```
