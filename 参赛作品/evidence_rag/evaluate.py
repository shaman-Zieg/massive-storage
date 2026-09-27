"""Labels are read only here, AFTER retrieval. No reference answers go to the RAG API."""
import json
import math
import platform
import random
import re
import time
import urllib.request
from copy import copy
from pathlib import Path

from .agent import Evidence
from .retrieval import Retriever

SPLIT_SEED = 20260927
PAGE_BUDGETS = (1, 3, 5, 6, 10, 20)
PACKED_METRICS = ("packed_text_hit", "packed_text_all_pages", "packed_text_page_recall")
EXPOSURE_NOTE = (
    "The 30 public questions and labels have previously been inspected. This document-grouped "
    "dev/holdout partition is a retrospective diagnostic, NOT a blind or independent test. "
    "Neither partition estimates hidden-test QA accuracy."
)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    temp.replace(path)


def ground_truth_pages(sample):
    result = set()
    for raw in sample.get("gt_image_paths", []):
        path = raw.replace("\\", "/")
        match = re.fullmatch(r"images/(.+)/([^/]+)/[^/]+_page_(\d+)\.png", path)
        if not match:
            raise ValueError(f"Unsupported reference page path: {path}")
        domain, ident, page = match.groups()
        result.add((domain.replace("/", "_")+"_"+ident, int(page)))
    if not result:
        raise ValueError("Sample has no reference pages")
    return result


def _metric_keys(rows):
    return sorted({key for row in rows for key, value in row.items()
                   if (key.startswith(("hit@", "all_pages@", "page_recall@")) or key in PACKED_METRICS)
                   and isinstance(value, (int, float)) and math.isfinite(value)})


def aggregate(rows):
    """Macro-average over questions; never treat an absent old-report metric as zero."""
    return {key: round(sum(row[key] for row in rows)/len(rows), 6)
            for key in _metric_keys(rows) if all(key in row for row in rows)} if rows else {}


def _documents(row):
    return {str(page[0]) for page in row.get("expected_pages", [])}


def _document_groups(rows):
    """Connect documents co-occurring in a question so no document crosses the split."""
    parent = {doc: doc for row in rows for doc in _documents(row)}

    def root(doc):
        while parent[doc] != doc:
            parent[doc] = parent[parent[doc]]
            doc = parent[doc]
        return doc

    for row in rows:
        docs = sorted(_documents(row))
        if not docs:
            raise ValueError("Document grouping requires nonempty expected_pages")
        for doc in docs[1:]:
            left, right = root(docs[0]), root(doc)
            parent[max(left, right)] = min(left, right)
    groups = {}
    for row in rows:
        groups.setdefault(root(min(_documents(row))), []).append(row)
    return {key: groups[key] for key in sorted(groups)}


def document_split(rows, seed=SPLIT_SEED, holdout_fraction=0.3):
    """Stable by document identity and seed, independent of question input order."""
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between 0 and 1")
    groups = _document_groups(rows)
    keys = list(groups)
    random.Random(seed).shuffle(keys)
    count = min(len(keys)-1, max(1, round(len(keys)*holdout_fraction))) if len(keys) > 1 else 0
    held = set(keys[:count])
    partitions = {name: [row for key, values in groups.items() if (key in held) == is_held for row in values]
                  for name, is_held in (("dev", False), ("holdout", True))}
    result = {"seed": seed, "holdout_fraction_by_document_group": holdout_fraction,
              "method": "Connected reference-document groups; shuffled sorted groups; disjoint documents",
              "label_exposure": EXPOSURE_NOTE, "document_groups": len(groups)}
    for name, values in partitions.items():
        result[name] = {"count": len(values), "documents": sorted({d for row in values for d in _documents(row)}),
                        "sample_ids": sorted((row.get("sample_id") for row in values), key=str),
                        "overall": aggregate(values)}
    if len(keys) < 2:
        result["warning"] = "Fewer than two independent document groups: holdout left empty."
    return result


def _percentile(values, probability):
    position = (len(values)-1)*probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper]-values[lower])*(position-lower)


def document_bootstrap(rows, seed=SPLIT_SEED, iterations=2000):
    """95% percentile intervals, sampling document groups with replacement.

    All questions in a sampled group travel together. The statistic is the
    question-weighted macro-average, so larger documents retain their weight.
    These intervals describe this exposed dataset, not generalization accuracy.
    """
    if iterations < 100:
        raise ValueError("At least 100 bootstrap resamples are required")
    if not rows:
        return {}
    groups = list(_document_groups(rows).values())
    metrics = [key for key in _metric_keys(rows) if all(key in row for row in rows)]
    totals = [{key: sum(row[key] for row in group) for key in metrics} for group in groups]
    rng, draws = random.Random(seed), {key: [] for key in metrics}
    for _ in range(iterations):
        selected = [rng.randrange(len(groups)) for _ in groups]
        denominator = sum(len(groups[i]) for i in selected)
        for key in metrics:
            draws[key].append(sum(totals[i][key] for i in selected)/denominator)
    return {key: {"estimate": aggregate(rows)[key],
                  "low": round(_percentile(sorted(values), 0.025), 6),
                  "high": round(_percentile(sorted(values), 0.975), 6),
                  "confidence": 0.95, "method": "document_group_percentile_bootstrap",
                  "document_groups": len(groups), "resamples": iterations,
                  "warning": "Too few document groups for a reliable interval" if len(groups) < 5 else None}
            for key, values in draws.items()}


def _page_measures(pages, expected):
    result = {}
    for k in PAGE_BUDGETS:
        selected = set(pages[:k])
        found = selected & expected
        result.update({f"hit@{k}": int(bool(found)), f"all_pages@{k}": int(expected <= selected),
                       f"page_recall@{k}": len(found)/len(expected)})
    return result


def _read_report(value):
    return json.loads(Path(value).read_text("utf-8")) if isinstance(value, (str, Path)) else value


def _index_rows(rows):
    indexed = {}
    for original in rows:
        row = dict(original)
        ident = row.get("sample_id")
        if ident is None or ident == "":
            raise ValueError("Paired evaluation requires a nonempty sample_id on every row")
        if ident in indexed:
            raise ValueError(f"Duplicate sample_id: {ident}")
        indexed[ident] = row
        # Old reports stored candidate lists through @20, enough to recover @6.
        # Packed evidence cannot be reconstructed from retrieval candidates.
        if row.get("expected_pages") and "retrieved_pages" in row:
            pages = [tuple(page) for page in row["retrieved_pages"]]
            expected = {tuple(page) for page in row["expected_pages"]}
            for key, value in _page_measures(pages, expected).items():
                row.setdefault(key, value)
    return indexed


def paired_comparison(baseline, candidate, seed=SPLIT_SEED, iterations=2000):
    """Read paths or reports, align sample IDs and bootstrap paired candidate-minus-baseline deltas."""
    baseline, candidate = _read_report(baseline), _read_report(candidate)
    before, after = _index_rows(baseline["details"]), _index_rows(candidate["details"])
    common = sorted(before.keys() & after.keys(), key=str)
    if not common:
        raise ValueError("Reports have no matching sample_id values")
    available_before, available_after = set(_metric_keys(list(before.values()))), set(_metric_keys(list(after.values())))
    metrics = sorted(available_before & available_after)
    metrics = [key for key in metrics if all(key in before[i] and key in after[i] for i in common)]
    deltas = []
    for ident in common:
        left, right = before[ident], after[ident]
        if left.get("question") != right.get("question"):
            raise ValueError(f"Question changed for sample_id {ident}")
        if {tuple(p) for p in left.get("expected_pages", [])} != {tuple(p) for p in right.get("expected_pages", [])}:
            raise ValueError(f"Reference pages changed for sample_id {ident}")
        deltas.append({"sample_id": ident, "expected_pages": right["expected_pages"],
                       **{key: right[key]-left[key] for key in metrics}})
    intervals = document_bootstrap(deltas, seed, iterations)
    result = {"direction": "candidate_minus_baseline", "matched_samples": len(common), "seed": seed,
              "baseline_only_ids": sorted(before.keys()-after.keys(), key=str),
              "candidate_only_ids": sorted(after.keys()-before.keys(), key=str),
              "metrics_not_comparable": sorted(available_before ^ available_after),
              "corpus_matches": (baseline["corpus_sha256"] == candidate["corpus_sha256"])
                                if baseline.get("corpus_sha256") and candidate.get("corpus_sha256") else None,
              "limitations": EXPOSURE_NOTE + " Paired intervals are descriptive; no multiple-comparison correction.",
              "metrics": {}}
    for key in metrics:
        changes = [row[key] for row in deltas]
        result["metrics"][key] = {"baseline": round(sum(before[i][key] for i in common)/len(common), 6),
                                  "candidate": round(sum(after[i][key] for i in common)/len(common), 6),
                                  "delta": round(sum(changes)/len(changes), 6),
                                  "improved": sum(value > 0 for value in changes),
                                  "regressed": sum(value < 0 for value in changes),
                                  "unchanged": sum(value == 0 for value in changes), "delta_ci95": intervals[key]}
    return result


def retrieval_report(config, questions, output, baseline=None, seed=SPLIT_SEED,
                     holdout_fraction=0.3, bootstrap_iterations=2000):
    samples = json.loads(Path(questions).read_text("utf-8"))
    started = time.perf_counter()
    retriever = Retriever(config, offline=True)
    load_seconds = time.perf_counter()-started
    # Use the production packer's text selection and truncation, without PDF
    # rendering/model calls. Only the question and retrieved evidence enter pack.
    pack_config = copy(config)
    pack_config.use_vision = False
    packing_load_started = time.perf_counter()
    evidence = Evidence(pack_config, retriever.corpus)
    packing_load_seconds = time.perf_counter()-packing_load_started
    details = []
    for sample in samples:
        start = time.perf_counter()
        result = retriever.search(sample["question"])
        elapsed = time.perf_counter()-start
        pages = [(p["doc"], p["page"]) for p in result["pages"]]
        packing_started = time.perf_counter()
        _, sources, pack_stats = evidence.pack(sample["question"], result["indices"], result["pages"],
                                               time.monotonic()+config.query_deadline)
        packing_seconds = time.perf_counter()-packing_started
        packed_pages = {(source["doc"], source["page"]) for source in sources.values()}
        # Labels are accessed only AFTER both search and evidence selection.
        expected = ground_truth_pages(sample)
        unknown = expected-set(retriever.corpus.by_page)
        if unknown:
            raise ValueError(f"Reference page not present in corpus: {unknown}")
        measures = _page_measures(pages, expected)
        measures.update({"packed_text_hit": int(bool(packed_pages & expected)),
                         "packed_text_all_pages": int(expected <= packed_pages),
                         "packed_text_page_recall": len(packed_pages & expected)/len(expected)})
        details.append({"sample_id": sample.get("sample_id"), "question": sample["question"],
            "domain": sample.get("domain"), "answer_type": sample.get("answer_type"),
            "expected_pages": sorted(expected), "retrieved_pages": pages[:20], "seconds": elapsed,
            "packed_text_pages": sorted(packed_pages), "packed_text_source_ids": list(sources),
            "packing_seconds": packing_seconds, "retrieval_and_packing_seconds": elapsed+packing_seconds,
            "pack_stats": pack_stats, **measures})
    timings = sorted(d["seconds"] for d in details)
    packing_timings = sorted(d["packing_seconds"] for d in details)
    combined_timings = sorted(d["retrieval_and_packing_seconds"] for d in details)
    report = {"schema_version": 2, "mode": "offline_retrieval_diagnostic", "answer_accuracy": None,
        "limitations": "No live embedding, reranking, VLM or answer judging. Retrieval hit rate is NOT QA accuracy. " + EXPOSURE_NOTE,
        "count": len(samples), "corpus_sha256": retriever.corpus.fingerprint,
        "python": platform.python_version(), "platform": platform.platform(),
        "use_graph": config.use_graph, "use_page_index": getattr(config, "use_page_index", False),
        "use_page_neighbors": getattr(config, "use_page_neighbors", False),
        "use_table_rows": getattr(config, "use_table_rows", False), "candidates": config.candidates,
        "load_seconds": round(load_seconds, 4), "mean_query_seconds": round(sum(timings)/max(1,len(timings)),4),
        "p95_query_seconds": round(timings[max(0,math.ceil(len(timings)*.95)-1)],4) if timings else None,
        "packing_load_seconds": round(packing_load_seconds, 4),
        "mean_packing_seconds": round(sum(packing_timings)/max(1, len(details)), 6),
        "p95_packing_seconds": round(packing_timings[math.ceil(len(details)*.95)-1], 6) if details else None,
        "mean_retrieval_and_packing_seconds": round(sum(combined_timings)/max(1, len(details)), 6),
        "p95_retrieval_and_packing_seconds": round(combined_timings[math.ceil(len(details)*.95)-1], 6) if details else None,
        "total_retrieval_and_packing_seconds": round(sum(combined_timings), 6),
        "timing_protocol": {
            "clock": "time.perf_counter wall-clock seconds; p95 uses the nearest-rank method",
            "scope": "Offline local CPU retrieval and text packing diagnostic only; NOT official query_time_s or end-to-end inference latency",
            "excluded": "Model calls, network, PDF rendering, image loading, answer generation, verification and initial index/packer loading",
            "combined_definition": "Per-question retrieval elapsed plus production text pack elapsed; neither labels nor bootstrap overhead included"},
        "overall": aggregate(details), "details": details,
        "evidence_protocol": {"mode": "production_pack_text_only", "use_vision": False,
            "evidence_blocks": config.evidence_blocks, "context_chars": config.context_chars,
            "configured_max_images": config.max_images,
            "note": "Packed page presence does not prove the needed block/value survived truncation. Visual and multiround coverage are unmeasured."},
        "candidate_page_budgets": {str(k): {metric: aggregate(details).get(f"{metric}@{k}")
                                             for metric in ("hit", "all_pages", "page_recall")} for k in (3, 6, 10)},
        "split": document_split(details, seed, holdout_fraction),
        "confidence_intervals": document_bootstrap(details, seed, bootstrap_iterations)}
    for field in ("domain", "answer_type"):
        kinds = sorted({d[field] for d in details}, key=lambda value: str(value))
        report["by_"+field] = {str(kind): aggregate([d for d in details if d[field] == kind]) for kind in kinds}
        report["count_by_"+field] = {str(kind): sum(d[field] == kind for d in details) for kind in kinds}
    report["by_document"] = {doc: {"count": len(rows), "overall": aggregate(rows)}
                             for doc in sorted({doc for row in details for doc in _documents(row)})
                             for rows in [[row for row in details if doc in _documents(row)]]}
    if baseline is not None:
        report["paired_comparison"] = paired_comparison(baseline, report, seed, bootstrap_iterations)
    save_json(output, report)
    return {k:v for k,v in report.items() if k!='details'}


def _positive_seconds(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number of seconds")
    return float(value)


def _build_timing(build_time_s=None, build_timings=None):
    if build_time_s is not None and build_timings is not None:
        raise ValueError("Choose either build_time_s or build_timings, not both")
    if build_timings is not None:
        source = Path(build_timings)
        value = json.loads(source.read_text("utf-8"))
        if not isinstance(value, dict) or "build_time" not in value:
            raise ValueError("Build timings JSON must contain build_time")
        return _positive_seconds(value["build_time"], "build_time"), str(source.resolve())
    if build_time_s is not None:
        return _positive_seconds(build_time_s, "build_time_s"), "explicit --build-time-s / build_time_s argument"
    return None, None


def benchmark(questions, url, output, timeout=300, *, build_time_s=None, build_timings=None):
    """Collect answers and official-schema timings without inventing build duration.

    The supplied build duration must cover the complete measured initialization
    and indexing pipeline, including model/vector/graph work. It is not the
    offline corpus.json build time. Official search_time is full client loop
    wall time, including HTTP and result persistence, not summed server timings.
    """
    build_seconds, build_source = _build_timing(build_time_s, build_timings)
    samples = json.loads(Path(questions).read_text("utf-8"))
    output = Path(output)
    manifest = {"official_scoring_ready": False, "complete": False,
                "expected_queries": len(samples), "queries_executed": 0,
                "build_time_source": build_source, "answer_accuracy": None,
                "readiness_scope": "Timing-input completeness only; official judging and hardware acceptance remain required",
                "missing_inputs": ["completed_benchmark"] + ([] if build_seconds is not None else ["measured_complete_build_time"]),
                "build_time_boundary": "Initialization plus complete corpus ingestion and required multimodal/vector/graph index construction; exclude source parsing when using supplied parsed inputs",
                "search_time_boundary": "Whole sequential question loop including HTTP requests and answer/trace persistence; excludes input loading, final timing/manifest writes and subsequent official judging"}
    # Invalidate a previous run before issuing requests, including on partial failure.
    save_json(output/"benchmark_manifest.json", manifest)
    save_json(output/"timings.json", {"official_scoring_ready": False, "queries_executed": 0})
    save_json(output/"query_timings.json", [])
    results, query_timings, start = [], [], time.perf_counter()
    for sample in samples:
        sent = time.perf_counter()
        request = urllib.request.Request(url, json.dumps({"question": sample["question"]}).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        request_seconds = _positive_seconds(time.perf_counter()-sent, "request_time_s")
        query_seconds = _positive_seconds(result["query_time_s"], "query_time_s")
        record = {**sample, "response": result["answer"], "pred": result["answer"], "extracted_res": "",
                  "query_time_s": query_seconds, "request_time_s": request_seconds,
                  "rag_status": result["status"], "citations": result["citations"]}
        results.append(record)
        query_timings.append({"index": len(results), "sample_id": sample.get("sample_id"),
                              "question": sample["question"], "query_time_s": query_seconds,
                              "request_time_s": request_seconds})
        save_json(output/"rag_answers.json", results)
        save_json(output/"traces"/f"{len(results):04d}.json", result)
        save_json(output/"query_timings.json", query_timings)
    search_seconds = _positive_seconds(time.perf_counter()-start, "search_time")
    ready = build_seconds is not None and bool(results)
    timings = {"search_time": search_seconds, "queries_executed": len(results), "query_count": len(results),
               "total_query_time_s": sum(row["query_time_s"] for row in results),
               "total_request_time_s": sum(row["request_time_s"] for row in results),
               "official_scoring_ready": ready, "answer_accuracy": None,
               "judging": "Run the unchanged official judge separately", "build_time_source": build_source}
    if build_seconds is not None:
        timings["build_time"] = build_seconds
    if results:
        timings["avg_query_time_s"] = timings["total_query_time_s"]/len(results)
        timings["avg_request_time_s"] = timings["total_request_time_s"]/len(results)
    manifest.update({"official_scoring_ready": ready, "complete": True, "queries_executed": len(results),
                     "missing_inputs": ([] if build_seconds is not None else ["measured_complete_build_time"])
                                       + ([] if results else ["nonempty_question_set"])})
    save_json(output/"timings.json", timings)
    save_json(output/"benchmark_manifest.json", manifest)
    return {"completed": len(results), "output": str(output), "accuracy": None,
            "official_scoring_ready": ready, "missing_inputs": manifest["missing_inputs"]}
