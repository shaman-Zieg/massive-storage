import argparse
import json
import sys
from pathlib import Path

from .models import Config, Models, ModelError


def main():
    parser = argparse.ArgumentParser(description="Evidence RAG competition implementation")
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    sub.add_parser("embed")
    sub.add_parser("doctor")
    p = sub.add_parser("search")
    p.add_argument("question")
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("ask")
    p.add_argument("question")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p = sub.add_parser("evaluate-retrieval")
    p.add_argument("--questions", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--no-graph", action="store_true")
    p = sub.add_parser("benchmark")
    p.add_argument("--questions", required=True)
    p.add_argument("--url", default="http://127.0.0.1:8080/query")
    p.add_argument("--output", required=True)
    args = parser.parse_args()
    cfg = Config.load(args.config)
    result = None
    if args.command == "build":
        from .index import build
        result = build(cfg.parsed_root, cfg.index_dir, cfg.legacy_storage)
    elif args.command == "embed":
        from .retrieval import embed_corpus
        result = embed_corpus(cfg, Models(cfg))
    elif args.command == "search":
        from .retrieval import Retriever
        retriever = Retriever(cfg, offline=args.offline)
        result = retriever.search(args.question, Models(cfg))
        result['evidence'] = [{key:retriever.corpus.nodes[i][key] for key in ('id','doc','page','kind','text')}
                              for i in result.pop('indices')[:12]]
    elif args.command == "ask":
        from .agent import Agent
        result = Agent(cfg).answer(args.question)
    elif args.command == "serve":
        from .server import serve
        serve(cfg, args.host, args.port)
    elif args.command == "evaluate-retrieval":
        from .evaluate import retrieval_report
        cfg.use_graph = not args.no_graph
        result = retrieval_report(cfg, args.questions, args.output)
    elif args.command == "benchmark":
        from .evaluate import benchmark
        result = benchmark(args.questions, args.url, args.output, cfg.query_deadline+30)
    elif args.command == "doctor":
        import importlib.util
        import shutil
        checks = {"numpy": bool(importlib.util.find_spec('numpy')),
                  "nano_vectordb": bool(importlib.util.find_spec('nano_vectordb')),
                  "Pillow": bool(importlib.util.find_spec('PIL')),
                  "pdftoppm": bool(shutil.which('pdftoppm')),
                  "corpus": (Path(cfg.index_dir)/'corpus.json').is_file()}
        cfg.request_timeout = 8
        cfg.query_deadline = 30
        model = Models(cfg)
        for name,call in [('embedding',lambda: model.embed(['service connectivity check'])),
                          ('rerank',lambda: model.rerank('check',['service check'])),
                          ('llm',lambda: model.chat('Return a JSON object only.', 'Return {"ok":true}', 40))]:
            try:
                call(); checks[name] = True
            except Exception as exc:
                checks[name] = type(exc).__name__
        result = {"checks": checks, "ready": all(v is True for v in checks.values()),
                  "note": "Connectivity check only; model identity and official hardware must be verified separately"}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['ready'] else 2
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ModelError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
