#!/bin/bash
PWD="rag-anything-experiments"
# Check if a command was provided
if [ $# -eq 0 ]; then
    echo "Usage:$0 <command>"
    echo "Available commands:"
    exit 1
fi

COMMAND=$1
echo "=== RUNNING COMMAND WITH CONFIG $DOTENV_FILE ===>"
cat $DOTENV_FILE
echo "<=== RUNNING COMMAND WITH CONFIG $DOTENV_FILE ==="
echo $COMMAND
case $COMMAND in
    test_connection)
        echo "Running connection testing..."
        uv run python $PWD/utils/llm_connection_helper.py
        ;;
    run_rag_server)
        echo "Running rag server..."
        uv run python $PWD/rag_scripts/rag_uvicorn_server_vllm.py
        ;;
    run_rag_build)
        echo "Running rag build storage..."
        uv run python $PWD/rag_scripts/rag_build_index_vllm.py
        ;;
    run_rag_unidocbench)
        echo "Running UniDoc-Bench ..."
        uv run python  $PWD/bench_scripts/UniDoc-Bench/run_unidocbench.py
        ;;
    run_raw_model)
        echo "Running UniDoc-Bench baseline model ..."
        uv run python $PWD/bench_scripts/UniDoc-Bench/run_raw_model.py
        ;;
    run_rag_eval_qwen_plus)
        echo "Running UniDoc-Bench judging ..."
        uv run python $PWD/utils/judger.py
        ;;
    run_raw_eval_qwen_plus)
        echo "Running UniDoc-Bench judging ..."
        uv run python $PWD/utils/judger_raw.py
        ;;
    convert_debug_info_to_md)
        echo "Running UniDoc-Bench judging ..."
        uv run python $PWD/utils/raw_data_to_md.py
        ;;
    convert_debug_info_to_md)
        echo "Running UniDoc-Bench judging ..."
        uv run python $PWD/utils/raw_data_to_md.py
        ;;
    parse_docs)
        echo "Running parsing docs"
        uv run python $PWD/utils/docs_parser.py
        ;;
    fix_paths)
        echo "Running fix "
        uv run python $PWD/utils/change_img_paths.py
        ;;
    calc_final_score)
        echo "Running calculation of final score "
        uv run python $PWD/rag_scripts/calculate_final_score.py
        ;;
    *)
        echo "Unknown command: $COMMAND"
        exit 1
        ;;
esac

status=$?
exit "$status"
