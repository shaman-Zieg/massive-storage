#!/bin/bash
PWD="rag-anything-experiments"
# Check if a command was provided
if [ $# -eq 0 ]; then
    echo "Usage:$0 <command>"
    echo "Available commands:"
    exit 1
fi

COMMAND=$1

case $COMMAND in
    unidocbench_full)
        bash $PWD/run.sh run_rag_unidocbench && \
        bash $PWD/run.sh run_raw_model && \
        bash $PWD/run.sh run_rag_eval_qwen_plus && \
        bash $PWD/run.sh run_raw_eval_qwen_plus
        ;;
    unidocbench_rag)
        if ! bash $PWD/run.sh run_rag_unidocbench; then
            exit 1
        fi
        if ! bash $PWD/run.sh run_rag_eval_qwen_plus; then
            exit 1
        fi
        if grep -Eq '^BASELINE_SEARCH_TIME=[^[:space:]]+' "$DOTENV_FILE" && \
           grep -Eq '^BASELINE_BUILD_TIME=[^[:space:]]+' "$DOTENV_FILE"; then
            bash $PWD/run.sh calc_final_score
        else
            echo "Skipping final score: BASELINE_SEARCH_TIME and BASELINE_BUILD_TIME are not configured."
        fi
        ;;
    unidocbench_eval)
        bash $PWD/run.sh run_rag_eval_qwen_plus
        ;;
    unidocbench_raw)
        bash $PWD/run.sh run_raw_model && \
        bash $PWD/run.sh run_raw_eval_qwen_plus
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Available commands:"
        exit 1
        ;;
esac

exit 0
