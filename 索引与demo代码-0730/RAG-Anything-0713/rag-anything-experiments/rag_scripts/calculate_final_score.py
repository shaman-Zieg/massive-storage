#!/usr/bin/env python3
"""
Calculate Final Score for RAG Benchmark

This script computes the final score factoring in both accuracy and performance
(build and search times) relative to baseline values.

Formula:
  final_score = 100 * accuracy - a * min((actual_search_time - baseline_search_time)/baseline_search_time,1)
                - b * min((actual_build_time - baseline_build_time)/baseline_build_time,1)

Usage:
  python calculate_final_score.py [--baseline_search_time X] [--baseline_build_time Y] \
                                 [--coefficient_a A] [--coefficient_b B]
"""

import os
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
dotenv_file = os.getenv('DOTENV_FILE', '.env')

load_dotenv(dotenv_path=dotenv_file, override=True)

# Benchmark configuration
BENCHMARK_NAME = os.getenv("BENCHMARK_NAME", "bench_output")
BENCHMARK_RESULTS_DIR = f"{BENCHMARK_NAME}_results"


def load_accuracy(summary_file_path):
    """
    Load accuracy from rag_answers_judged_summary.json.

    Args:
        summary_file_path: Path to the summary JSON file

    Returns:
        accuracy: float value from 0.0 to 1.0
    """
    if not os.path.exists(summary_file_path):
        raise FileNotFoundError(f"Summary file not found: {summary_file_path}")

    with open(summary_file_path, 'r') as f:
        summary_data = json.load(f)

    # Try to get accuracy from different possible locations
    if "overall" in summary_data and "accuracy" in summary_data["overall"]:
        accuracy = summary_data["overall"]["accuracy"]
    elif "accuracy" in summary_data:
        accuracy = summary_data["accuracy"]
    else:
        raise ValueError(f"Could not find accuracy in {summary_file_path}")

    return accuracy


def load_timings(timings_file_path):
    """
    Load build_time and search_time from timings.json.

    Args:
        timings_file_path: Path to timings.json

    Returns:
        tuple: (build_time, search_time)
    """
    if not os.path.exists(timings_file_path):
        raise FileNotFoundError(f"Timings file not found: {timings_file_path}")

    with open(timings_file_path, 'r') as f:
        timings = json.load(f)

    if "build_time" not in timings or "search_time" not in timings:
        raise ValueError(f"Missing required fields in {timings_file_path}. "
                         f"Expected 'build_time' and 'search_time'")

    return timings["build_time"], timings["search_time"]


def calculate_final_score(accuracy, actual_build_time, actual_search_time,
                          baseline_build_time, baseline_search_time,
                          coefficient_a, coefficient_b):
    """
    Calculate final score based on accuracy and performance penalties.

    Formula:
      final_score = accuracy - a * (actual_search_time - baseline_search_time)/baseline_search_time
                    - b * (actual_build_time - baseline_build_time)/baseline_build_time

    Args:
        accuracy: float from 0.0 to 1.0
        actual_build_time: float (seconds)
        actual_search_time: float (seconds)
        baseline_build_time: float (seconds)
        baseline_search_time: float (seconds)
        coefficient_a: float (penalty weight for search time)
        coefficient_b: float (penalty weight for build time)

    Returns:
        float: final score
    """
    # Calculate search time penalty
    if baseline_search_time > 0:
        search_penalty = coefficient_a * min((actual_search_time - baseline_search_time) / baseline_search_time, 1)
    else:
        search_penalty = 0
        print("⚠️ Warning: baseline_search_time is 0, ignoring search penalty")

    # Calculate build time penalty
    if baseline_build_time > 0:
        build_penalty = coefficient_b * min((actual_build_time - baseline_build_time) / baseline_build_time, 1)
    else:
        build_penalty = 0
        print("⚠️ Warning: baseline_build_time is 0, ignoring build penalty")

    # Calculate final score
    final_score = accuracy*100 - search_penalty - build_penalty

    return final_score


def main():
    parser = argparse.ArgumentParser(
        description="Calculate final score for RAG benchmark"
    )
    parser.add_argument(
        "--baseline_search_time",
        type=float,
        default=float(os.getenv("BASELINE_SEARCH_TIME", "0")),
        help="Baseline search time in seconds (default: env BASELINE_SEARCH_TIME or 0)"
    )
    parser.add_argument(
        "--baseline_build_time",
        type=float,
        default=float(os.getenv("BASELINE_BUILD_TIME", "0")),
        help="Baseline build time in seconds (default: env BASELINE_BUILD_TIME or 0)"
    )
    parser.add_argument(
        "--coefficient_a",
        type=float,
        default=float(os.getenv("COEFFICIENT_A", "1.0")),
        help="Coefficient A for search time penalty (default: env COEFFICIENT_A or 1.0)"
    )
    parser.add_argument(
        "--coefficient_b",
        type=float,
        default=float(os.getenv("COEFFICIENT_B", "5.0")),
        help="Coefficient B for build time penalty (default: env COEFFICIENT_B or 5.0)"
    )
    parser.add_argument(
        "--summary_file",
        type=str,
        default=None,
        help=f"Path to rag_answers_judged_summary.json "
             f"(default: {BENCHMARK_RESULTS_DIR}/rag_answers_judged_summary.json)"
    )
    parser.add_argument(
        "--timings_file",
        type=str,
        default=None,
        help=f"Path to timings.json "
             f"(default: {BENCHMARK_RESULTS_DIR}/timings.json)"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help=f"Output path for final_scores.json "
             f"(default: {BENCHMARK_RESULTS_DIR}/final_scores.json)"
    )
    args = parser.parse_args()

    # Set default file paths
    if args.summary_file is None:
        args.summary_file = os.path.join(BENCHMARK_RESULTS_DIR, "rag_answers_judged_summary.json")

    if args.timings_file is None:
        args.timings_file = os.path.join(BENCHMARK_RESULTS_DIR, "timings.json")

    if args.output_file is None:
        args.output_file = os.path.join(BENCHMARK_RESULTS_DIR, "final_scores.json")

    # Verify defaults are provided
    if args.baseline_search_time == 0:
        raise ValueError("baseline_search_time must be provided (via --baseline_search_time or BASELINE_SEARCH_TIME env var)")

    if args.baseline_build_time == 0:
        raise ValueError("baseline_build_time must be provided (via --baseline_build_time or BASELINE_BUILD_TIME env var)")

    print("=" * 80)
    print("📊 RAG Final Score Calculator")
    print("=" * 80)

    # Load data
    print(f"\n📁 Loading data from {BENCHMARK_RESULTS_DIR}...")
    print(f"  - Summary file: {args.summary_file}")

    try:
        accuracy = load_accuracy(args.summary_file)
    except FileNotFoundError:
        print(f"❌ Error: {args.summary_file} not found.")
        print("   Make sure to run the judger script first:")
        print(f"   python utils/judger.py --input_path {BENCHMARK_RESULTS_DIR}/rag_answers.json")
        return 1
    except Exception as e:
        print(f"❌ Error loading accuracy: {e}")
        return 1

    print(f"  - Timings file: {args.timings_file}")

    try:
        actual_build_time, actual_search_time = load_timings(args.timings_file)
    except FileNotFoundError:
        print(f"❌ Error: {args.timings_file} not found.")
        print("   Make sure to run the build and benchmark scripts first.")
        return 1
    except Exception as e:
        print(f"❌ Error loading timings: {e}")
        return 1

    # Calculate final score
    print(f"\n📈 Calculating final score...")
    print(f"  Accuracy:                {accuracy:.4f}")
    print(f"  Actual build time:       {actual_build_time:.2f}s")
    print(f"  Actual search time:      {actual_search_time:.2f}s")
    print(f"  Baseline build time:     {args.baseline_build_time:.2f}s")
    print(f"  Baseline search time:    {args.baseline_search_time:.2f}s")
    print(f"  Coefficient A (search):  {args.coefficient_a}")
    print(f"  Coefficient B (build):   {args.coefficient_b}")

    final_score = calculate_final_score(
        accuracy=accuracy,
        actual_build_time=actual_build_time,
        actual_search_time=actual_search_time,
        baseline_build_time=args.baseline_build_time,
        baseline_search_time=args.baseline_search_time,
        coefficient_a=args.coefficient_a,
        coefficient_b=args.coefficient_b
    )

    # Prepare output
    result = {
        "final_score": round(final_score, 4),
        "accuracy": round(accuracy, 4),
        "actual_build_time": round(actual_build_time, 2),
        "baseline_build_time": round(args.baseline_build_time, 2),
        "actual_search_time": round(actual_search_time, 2),
        "baseline_search_time": round(args.baseline_search_time, 2),
        "coefficient_a": args.coefficient_a,
        "coefficient_b": args.coefficient_b,
        "search_time_penalty": round(
            args.coefficient_a * (actual_search_time - args.baseline_search_time) /
            args.baseline_search_time, 4
        ) if args.baseline_search_time > 0 else 0,
        "build_time_penalty": round(
            args.coefficient_b * (actual_build_time - args.baseline_build_time) /
            args.baseline_build_time, 4
        ) if args.baseline_build_time > 0 else 0
    }

    # Save output
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    with open(args.output_file, 'w') as f:
        json.dump(result, f, indent=2)

    # Print results
    print(f"\n{'='*80}")
    print("📊 FINAL RESULTS")
    print(f"{'='*80}")
    print(f"Final Score:        {result['final_score']:.4f}")
    print(f"Score Breakdown:")
    print(f"  Accuracy:          +{accuracy:.4f}")
    search_pen = result['search_time_penalty']
    build_pen = result['build_time_penalty']
    print(f"  Search penalty:    {search_pen:+.4f}")
    print(f"  Build penalty:     {build_pen:+.4f}")
    print(f"{'='*80}")
    print(f"📝 Results saved to: {args.output_file}")

    return 0


if __name__ == "__main__":
    exit(main())
