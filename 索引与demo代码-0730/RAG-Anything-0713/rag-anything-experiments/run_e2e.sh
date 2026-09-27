#!/bin/bash
cp rag-anything-experiments/.env ./
echo "Parsing and building index..."
DOTENV_FILE=.env bash rag-anything-experiments/run.sh parse_docs && DOTENV_FILE=.env bash rag-anything-experiments/run.sh fix_paths && \
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_build && \
DOTENV_FILE=.env bash rag-anything-experiments/run.sh run_rag_server & 
sleep 10
echo "Starting benchmark..."
DOTENV_FILE=.env bash rag-anything-experiments/start.sh unidocbench_rag && kill -9 $(pgrep -f rag_uvicorn_server_vllm.py)