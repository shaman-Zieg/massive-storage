import os
import re
import math
import json
import argparse
import time
#import fitz
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
from tqdm import tqdm
import requests
from dotenv import load_dotenv
dotenv_file = os.getenv('DOTENV_FILE', '.env')

load_dotenv(dotenv_path=dotenv_file, override=True)

# Benchmark configuration
BENCHMARK_NAME = os.getenv("BENCHMARK_NAME", "UniDoc-Bench")
BENCHMARK_RESULTS_DIR = f"{BENCHMARK_NAME}_results"
BENCH_FORCE_RERUN = os.getenv("BENCH_FORCE_RERUN", "false").lower() == "true"

def send_request_to_rag(q):
    query = {"question" : q}
    request_start = time.perf_counter()
    response = requests.post(os.getenv("RAG_BINDING_HOST", ""), json=query)
    request_time = time.perf_counter() - request_start
    response.raise_for_status()
    result = response.json()
    print(
        " send request to rag: "
        f"query_time={result.get('query_time_s')}s, "
        f"request_time={request_time:.3f}s"
    )
    return result["answer"], result.get("query_time_s"), round(request_time, 4)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_questions(args):
    # Ensure results directory exists
    os.makedirs(BENCHMARK_RESULTS_DIR, exist_ok=True)

    print(f"Output path: {args.output_path}")
    os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
    if os.path.exists(args.output_path) and not BENCH_FORCE_RERUN:
        with open(args.output_path) as f:
            samples = json.load(f)
    else:
        with open(args.input_path, 'r') as f:
            samples = json.load(f)

    if BENCH_FORCE_RERUN:
        print("Force rerun enabled: ignoring existing benchmark answers.")
        save_json(args.output_path, samples)

    # Track search time
    search_start_time = time.time()
    executed_queries = 0

    for sample in tqdm(samples):
        has_query_timings = (
            "query_time_s" in sample and "request_time_s" in sample
        )
        if "score" not in sample or not has_query_timings:
            response, query_time, request_time = send_request_to_rag(
                sample["question"]
            )

            sample["response"] = response
            sample["extracted_res"] = ""
            sample["pred"] = response
            sample["score"] = 0
            sample["query_time_s"] = query_time
            sample["request_time_s"] = request_time
            executed_queries += 1

            # Keep completed samples if a later request fails.
            save_json(args.output_path, samples)

    save_json(args.output_path, samples)

    # Calculate and save search time
    search_time = time.time() - search_start_time

    # Save or update timings.json
    timings_file = os.path.join(BENCHMARK_RESULTS_DIR, "timings.json")
    timings = {}
    if os.path.exists(timings_file):
        with open(timings_file, "r") as f:
            timings = json.load(f)

    if executed_queries:
        timings["search_time"] = round(search_time, 2)
    timings["queries_executed"] = executed_queries
    query_times = [
        sample["query_time_s"]
        for sample in samples
        if isinstance(sample.get("query_time_s"), (int, float))
    ]
    request_times = [
        sample["request_time_s"]
        for sample in samples
        if isinstance(sample.get("request_time_s"), (int, float))
    ]
    timings["query_count"] = len(query_times)
    if query_times:
        timings["total_query_time_s"] = round(sum(query_times), 4)
        timings["avg_query_time_s"] = round(sum(query_times) / len(query_times), 4)
    if request_times:
        timings["total_request_time_s"] = round(sum(request_times), 4)
        timings["avg_request_time_s"] = round(
            sum(request_times) / len(request_times), 4
        )

    save_json(timings_file, timings)

    query_timings = [
        {
            "index": index,
            "sample_id": sample.get("sample_id"),
            "question": sample.get("question"),
            "query_time_s": sample.get("query_time_s"),
            "request_time_s": sample.get("request_time_s"),
        }
        for index, sample in enumerate(samples, start=1)
    ]
    query_timings_file = os.path.join(
        BENCHMARK_RESULTS_DIR, "query_timings.json"
    )
    save_json(query_timings_file, query_timings)

    if executed_queries:
        print(
            f"\n⏱️ Total search time for {executed_queries} queries: "
            f"{search_time:.2f}s"
        )
    else:
        print("\n⏭️ No queries executed; existing per-query timings were kept.")
    print(f"📝 Search time saved to: {timings_file}")
    print(f"📝 Per-query timings saved to: {query_timings_file}")


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench_name", type=str, default=BENCHMARK_NAME)
    parser.add_argument("--input_path", type=str, default=os.getenv("BENCH_QUERIES", ""))
    parser.add_argument("--output_path", type=str, default=os.path.join(BENCHMARK_RESULTS_DIR, "rag_answers.json"))
    args = parser.parse_args()

    load_questions(args)
