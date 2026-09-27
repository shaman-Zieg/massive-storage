"""Labels are read only here, AFTER retrieval. No reference answers go to the RAG API."""
import json
import math
import platform
import re
import time
import urllib.request
from pathlib import Path

from .retrieval import Retriever


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


def retrieval_report(config, questions, output):
    samples = json.loads(Path(questions).read_text("utf-8"))
    started = time.perf_counter()
    retriever = Retriever(config, offline=True)
    load_seconds = time.perf_counter()-started
    details = []
    for sample in samples:
        start = time.perf_counter()
        result = retriever.search(sample["question"])
        elapsed = time.perf_counter()-start
        pages = [(p["doc"], p["page"]) for p in result["pages"]]
        expected = ground_truth_pages(sample)
        unknown = expected-set(retriever.corpus.by_page)
        if unknown:
            raise ValueError(f"Reference page not present in corpus: {unknown}")
        measures = {}
        for k in (1,3,5,10,20):
            found = set(pages[:k]) & expected
            measures[f"hit@{k}"] = int(bool(found))
            measures[f"all_pages@{k}"] = int(expected <= set(pages[:k]))
            measures[f"page_recall@{k}"] = len(found)/len(expected)
        details.append({"sample_id": sample.get("sample_id"), "question": sample["question"],
            "domain": sample.get("domain"), "answer_type": sample.get("answer_type"),
            "expected_pages": sorted(expected), "retrieved_pages": pages[:20], "seconds": elapsed, **measures})
    def aggregate(rows):
        return {key: round(sum(row[key] for row in rows)/len(rows), 6)
                for key in rows[0] if "@" in key} if rows else {}
    timings = sorted(d["seconds"] for d in details)
    report = {"mode": "offline_retrieval_diagnostic", "answer_accuracy": None,
        "limitations": "No live embedding, reranking, VLM or answer judging. Retrieval hit rate is NOT QA accuracy. Public development set only.",
        "count": len(samples), "corpus_sha256": retriever.corpus.fingerprint,
        "python": platform.python_version(), "platform": platform.platform(),
        "use_graph": config.use_graph, "candidates": config.candidates,
        "load_seconds": round(load_seconds, 4), "mean_query_seconds": round(sum(timings)/max(1,len(timings)),4),
        "p95_query_seconds": round(timings[max(0,math.ceil(len(timings)*.95)-1)],4) if timings else None,
        "overall": aggregate(details), "by_answer_type": {kind: aggregate([d for d in details if d['answer_type']==kind])
              for kind in sorted({d['answer_type'] for d in details})}, "details": details}
    save_json(output, report)
    return {k:v for k,v in report.items() if k!='details'}


def benchmark(questions, url, output, timeout=300):
    samples = json.loads(Path(questions).read_text("utf-8"))
    results, start = [], time.perf_counter()
    for sample in samples:
        sent = time.perf_counter()
        request = urllib.request.Request(url, json.dumps({"question": sample["question"]}).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        record = {**sample, "response": result["answer"], "pred": result["answer"], "extracted_res": "",
                  "query_time_s": result["query_time_s"], "request_time_s": time.perf_counter()-sent,
                  "rag_status": result["status"], "citations": result["citations"]}
        results.append(record)
        save_json(Path(output)/"rag_answers.json", results)
        save_json(Path(output)/"traces"/f"{len(results):04d}.json", result)
    save_json(Path(output)/"timings.json", {"search_time": time.perf_counter()-start,
        "queries_executed": len(results), "answer_accuracy": None, "judging": "Run the unchanged official judge separately"})
    return {"completed": len(results), "output": str(output), "accuracy": None}
