import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


def parse_env_file(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def write_env_file(base_lines: list[str], output_path: Path, overrides: dict[str, str]) -> None:
    seen: set[str] = set()
    output_lines: list[str] = []

    for line in base_lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in overrides:
                output_lines.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
        output_lines.append(line)

    for key, value in overrides.items():
        if key not in seen:
            output_lines.append(f"{key}={value}")

    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


def prepare_subset(source_root: Path, subset_root: Path, selected_jsons: list[Path]) -> None:
    if subset_root.exists():
        shutil.rmtree(subset_root)
    subset_root.mkdir(parents=True, exist_ok=True)

    for src in selected_jsons:
        rel = src.relative_to(source_root)
        dst = subset_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def read_status(storage_dir: Path) -> tuple[int, int, int]:
    status_file = storage_dir / "kv_store_doc_status.json"
    if not status_file.exists():
        return 0, 0, 0

    data = json.loads(status_file.read_text(encoding="utf-8"))
    processed = 0
    failed = 0
    total = 0
    for item in data.values():
        if not isinstance(item, dict):
            continue
        total += 1
        status = item.get("status")
        if status == "processed":
            processed += 1
        elif status == "failed":
            failed += 1
    return total, processed, failed


def log_has_fatal_error(log_path: Path) -> bool:
    if not log_path.exists():
        return True

    fatal_markers = (
        "❌ Failed [",
        "Failed to extract document",
        "Worker execution timeout",
        "OpenAI API Timeout Error",
        "Error in multimodal processing",
        "Traceback (most recent call last)",
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    return any(marker in log_text for marker in fatal_markers)


def read_selected_file_list(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    selected: list[str] = []
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        selected.append(item)
    return selected


def find_content_list(source_root: Path, item: str) -> Path:
    candidate = Path(item)
    if candidate.suffix == ".json":
        if candidate.is_absolute():
            return candidate
        return source_root / candidate

    pdf_name = candidate.name if candidate.suffix == ".pdf" else f"{candidate.name}.pdf"
    stem = pdf_name[:-4]
    matches = sorted(source_root.rglob(f"{stem}_content_list.json"))
    if not matches:
        raise SystemExit(f"Selected file not found under {source_root}: {item}")
    if len(matches) > 1:
        raise SystemExit(f"Selected file matched multiple content lists: {item}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark RAG index build time for multiple document counts."
    )
    parser.add_argument("--base-env", default=".env", help="Base .env file to copy")
    parser.add_argument(
        "--sizes",
        default="2,4,6,8,10",
        help="Comma-separated document counts to benchmark",
    )
    parser.add_argument(
        "--source-dir",
        default=None,
        help="Directory containing *_content_list.json files. Defaults to DOC_FILE_PATH from base env.",
    )
    parser.add_argument(
        "--output-root",
        default="index_build_benchmarks",
        help="Directory for benchmark envs, logs, subset inputs, and storages",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Run directory prefix. Defaults to timestamp.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue to the next size even if one build command fails.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help=(
            "Maximum attempts for each size. Every retry uses a new storage directory; "
            "only a complete, error-free attempt is accepted."
        ),
    )
    parser.add_argument(
        "--selected-files",
        default=None,
        help=(
            "Optional text file containing one PDF name or *_content_list.json path per line. "
            "When set, benchmark sizes use this order instead of directory order."
        ),
    )
    args = parser.parse_args()
    if args.max_attempts <= 0:
        raise SystemExit("--max-attempts must be greater than zero")

    repo_root = Path.cwd()
    base_env = Path(args.base_env)
    if not base_env.exists():
        raise SystemExit(f"Base env not found: {base_env}")

    base_lines, base_values = parse_env_file(base_env)
    source_root = Path(args.source_dir or base_values.get("DOC_FILE_PATH", "")).resolve()
    if not source_root.exists():
        raise SystemExit(f"Source DOC_FILE_PATH does not exist: {source_root}")

    sizes = [int(x.strip()) for x in args.sizes.split(",") if x.strip()]
    if not sizes or any(size <= 0 for size in sizes):
        raise SystemExit(f"Invalid --sizes: {args.sizes}")

    skip_file_names = {
        item.strip()
        for item in base_values.get("SKIP_FILE_PATHS", "").split(",")
        if item.strip()
    }
    if args.selected_files:
        selected_items = read_selected_file_list(Path(args.selected_files))
        all_jsons = []
        seen_jsons: set[Path] = set()
        for item in selected_items:
            json_path = find_content_list(source_root, item).resolve()
            file_ref = json_path.stem.replace("_content_list", "")
            pdf_file_name = f"{file_ref}.pdf"
            if pdf_file_name in skip_file_names:
                continue
            if json_path in seen_jsons:
                continue
            seen_jsons.add(json_path)
            all_jsons.append(json_path)
    else:
        all_jsons = []
        for json_path in sorted(source_root.rglob("*_content_list.json")):
            file_ref = json_path.stem.replace("_content_list", "")
            pdf_file_name = f"{file_ref}.pdf"
            if pdf_file_name in skip_file_names:
                continue
            all_jsons.append(json_path)
    if len(all_jsons) < max(sizes):
        raise SystemExit(
            f"Not enough content_list files under {source_root}: "
            f"found {len(all_jsons)}, need {max(sizes)}"
        )

    stamp = args.prefix or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.output_root) / stamp
    env_dir = run_root / "envs"
    log_dir = run_root / "logs"
    subset_dir = run_root / "subsets"
    storage_dir = run_root / "storages"
    for path in [env_dir, log_dir, subset_dir, storage_dir]:
        path.mkdir(parents=True, exist_ok=True)

    selected_manifest = run_root / "selected_files.json"
    selected_manifest.write_text(
        json.dumps(
            [str(path.relative_to(source_root)) for path in all_jsons[: max(sizes)]],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    results: list[dict[str, object]] = []

    for size in sizes:
        bench_name = f"index_{size:02d}_docs"
        current_subset_dir = subset_dir / bench_name
        current_log_dir = log_dir / bench_name
        current_env = env_dir / f"{bench_name}.env"
        current_log_dir.mkdir(parents=True, exist_ok=True)

        prepare_subset(source_root, current_subset_dir, all_jsons[:size])

        accepted = False
        attempts: list[dict[str, object]] = []
        for attempt in range(1, args.max_attempts + 1):
            attempt_name = f"attempt_{attempt:02d}"
            current_storage_dir = storage_dir / bench_name / attempt_name
            attempt_log_dir = current_log_dir / attempt_name
            attempt_env = env_dir / f"{bench_name}_{attempt_name}.env"
            log_path = attempt_log_dir / "run_rag_build.log"
            attempt_log_dir.mkdir(parents=True, exist_ok=True)

            if current_storage_dir.exists():
                raise SystemExit(
                    f"Refusing to overwrite existing storage: {current_storage_dir}"
                )

            overrides = {
                "DOC_FILE_PATH": str(current_subset_dir),
                "RAG_STORAGE": str(current_storage_dir),
                "LOG_DIR": str(attempt_log_dir),
                "BENCHMARK_NAME": f"BENCH_{bench_name}_{attempt_name}",
            }
            write_env_file(base_lines, attempt_env, overrides)

            env = os.environ.copy()
            env["DOTENV_FILE"] = str(attempt_env)

            print("=" * 80, flush=True)
            print(f"Benchmark size={size}, attempt={attempt}/{args.max_attempts}", flush=True)
            print(f"DOC_FILE_PATH={current_subset_dir}", flush=True)
            print(f"RAG_STORAGE={current_storage_dir}", flush=True)
            print(f"LOG={log_path}", flush=True)

            start = time.perf_counter()
            with log_path.open("w", encoding="utf-8") as log_file:
                proc = subprocess.run(
                    ["bash", "rag-anything-experiments/run.sh", "run_rag_build"],
                    cwd=repo_root,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            elapsed = time.perf_counter() - start
            total_status, processed_status, failed_status = read_status(
                current_storage_dir
            )
            fatal_error = log_has_fatal_error(log_path)
            accepted = (
                proc.returncode == 0
                and processed_status == size
                and failed_status == 0
                and not fatal_error
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "elapsed_sec": round(elapsed, 3),
                    "returncode": proc.returncode,
                    "processed": processed_status,
                    "failed": failed_status,
                    "fatal_error_in_log": fatal_error,
                    "accepted": accepted,
                    "storage_dir": str(current_storage_dir),
                    "log_file": str(log_path),
                }
            )
            print(
                f"Attempt {attempt}: elapsed={elapsed:.3f}s "
                f"processed={processed_status}/{size} failed={failed_status} "
                f"fatal_log={fatal_error} accepted={accepted}",
                flush=True,
            )
            if accepted:
                break
            if attempt < args.max_attempts:
                print("Retrying with a fresh isolated storage directory.", flush=True)

        result = {
            "size": size,
            "valid": accepted,
            "elapsed_sec": round(elapsed, 3) if accepted else None,
            "attempt_count": len(attempts),
            "returncode": proc.returncode,
            "storage_dir": str(current_storage_dir),
            "doc_file_path": str(current_subset_dir),
            "env_file": str(attempt_env),
            "log_file": str(log_path),
            "doc_status_total": total_status,
            "doc_status_processed": processed_status,
            "doc_status_failed": failed_status,
            "attempts": json.dumps(attempts, ensure_ascii=False),
        }
        results.append(result)

        summary_path = run_root / "summary.json"
        summary_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        csv_path = run_root / "summary.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

        print(
            f"Done size={size}: valid={accepted} "
            f"elapsed={elapsed:.3f}s processed={processed_status}/{size}",
            flush=True,
        )

        if not accepted and not args.keep_going:
            print(
                f"Stopping: size={size} did not complete cleanly after "
                f"{args.max_attempts} attempts. See: {current_log_dir}",
                flush=True,
            )
            return 1

    print("=" * 80, flush=True)
    print(f"Benchmark summary: {run_root / 'summary.csv'}", flush=True)
    print(f"Benchmark details: {run_root / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
