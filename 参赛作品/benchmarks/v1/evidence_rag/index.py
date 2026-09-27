"""Deterministic corpus ingestion. Never reads QA, answers or evaluation labels."""
from __future__ import annotations

import collections
import hashlib
import html
import json
import math
import re
import time
import unicodedata
from pathlib import Path

STOP = set("a an and are as at be been between by can did do does for from had has have how i if in into is it its of on or that the their these this those to was were what when where which who why will with would according described detailed shown figure table report page".split())


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", html.unescape(re.sub(r"<[^>]*>", " ", text))).lower()
    greek = dict(zip("αβγδεζηθικλμνξοπρστυφχψω", "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega".split()))
    # Align Unicode symbols in questions with LaTeX names in parsed formulas.
    text = "".join(" "+greek[ch]+" " if ch in greek else ch for ch in text)
    out = []
    for word in re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*|[\u4e00-\u9fff]+", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            out.extend(word[i:i+2] for i in range(max(1, len(word)-1)))
        elif word not in STOP:
            if len(word) > 5 and word.endswith("ies"):
                word = word[:-3] + "y"
            elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
                word = word[:-1]
            out.append(word)
    return out


class BM25:
    def __init__(self, texts):
        self.postings = collections.defaultdict(list)
        self.lengths = []
        for i, text in enumerate(texts):
            counts = collections.Counter(tokens(text))
            self.lengths.append(sum(counts.values()))
            for token, count in counts.items():
                self.postings[token].append((i, count))
        self.n = len(self.lengths)
        self.avg = sum(self.lengths) / max(1, self.n)

    def search(self, query, k=60, allowed=None):
        scores = collections.defaultdict(float)
        for token in set(tokens(query)):
            posting = self.postings.get(token, ())
            idf = math.log(1 + (self.n-len(posting)+0.5)/(len(posting)+0.5))
            for i, tf in posting:
                if allowed is not None and i not in allowed:
                    continue
                scores[i] += idf * tf * 2.2 / (tf + 1.2*(0.25+0.75*self.lengths[i]/max(self.avg, 1)))
        return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:k]


def safe_file(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Source path escapes configured corpus root")
    return path


def block_text(block):
    parts = [block.get("text", "")]
    for key in ("image_caption", "image_footnote", "table_caption", "table_footnote"):
        value = block.get(key, [])
        parts.extend(value if isinstance(value, list) else [value])
    # Preserve HTML rowspan/colspan in evidence. Plain text view is only for retrieval.
    parts.append(block.get("table_body", ""))
    return "\n".join(str(p).strip() for p in parts if p).strip()


def build(parsed_root, output, legacy_storage=None):
    started = time.perf_counter()
    root, output = Path(parsed_root).resolve(), Path(output)
    files = sorted(root.glob("*/auto/*_content_list.json"))
    if not files:
        raise ValueError("No */auto/*_content_list.json found")
    # Only descriptions of source images, never caches of question-answer responses.
    descriptions = collections.defaultdict(list)
    if legacy_storage:
        legacy = json.loads((Path(legacy_storage)/"kv_store_text_chunks.json").read_text("utf-8"))
        for item in legacy.values():
            content = item.get("content", "")
            match = re.search(r"Image Path:\s*([^\r\n]+)", content)
            if match:
                image_name = Path(match.group(1).replace("\\", "/")).name
                descriptions[image_name].append(content)
    nodes, documents, counts = [], {}, collections.Counter()
    manifest = []
    for file in files:
        doc = file.parent.parent.name
        blocks = json.loads(file.read_text("utf-8"))
        titles = [b.get("text", "") for b in blocks if b.get("text_level") == 1][:3]
        title = " ".join(titles)[:500]
        documents[doc] = {"title": title, "pages": 1+max((b.get("page_idx", 0) for b in blocks), default=0)}
        manifest.append({"path": file.relative_to(root).as_posix(), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        section = title
        for ordinal, block in enumerate(blocks):
            kind = block.get("type", "text")
            counts[kind] += 1
            text = block_text(block)
            if block.get("text_level") == 1:
                section = block.get("text", section)
            raw_img = str(block.get("img_path", "")).replace("\\", "/")
            image_rel = ""
            if raw_img:
                candidate = file.parent / "images" / Path(raw_img).name
                if candidate.is_file():
                    image_rel = candidate.relative_to(root).as_posix()
            enriched = "\n".join(descriptions.get(Path(raw_img).name, []))[:16000] if raw_img else ""
            # Stable identifiers survive root relocation; page is one-based throughout runtime.
            ident = f"{doc}:p{block.get('page_idx', 0)+1}:b{ordinal}"
            nodes.append({"id": ident, "doc": doc, "page": block.get("page_idx", 0)+1,
                          "kind": kind, "ordinal": ordinal, "bbox": block.get("bbox"),
                          "title": title, "section": section, "text": text,
                          "description": enriched, "image": image_rel})
    by_page, by_doc = collections.defaultdict(list), collections.defaultdict(list)
    captions = {}
    for i, node in enumerate(nodes):
        by_page[(node["doc"], node["page"])].append(i)
        by_doc[node["doc"]].append(i)
        if node["kind"] != "text":
            for label in re.findall(r"\b(fig(?:ure)?\.?\s*\d+|table\s*\d+)\b", node["text"], re.I):
                captions[(node["doc"], re.sub(r"\W", "", label.lower()).replace("figure", "fig"))] = i
    edges = collections.defaultdict(set)
    for indices in by_page.values():
        for i in indices:
            # Typed layout links: nearby blocks and all visual blocks on the same page.
            edges[i].update(j for j in indices if j != i and (abs(j-i) <= 2 or nodes[j]["kind"] != "text"))
    for i, node in enumerate(nodes):
        for label in re.findall(r"\b(fig(?:ure)?\.?\s*\d+|table\s*\d+)\b", node["text"], re.I):
            key = (node["doc"], re.sub(r"\W", "", label.lower()).replace("figure", "fig"))
            if key in captions and captions[key] != i:
                edges[i].add(captions[key]); edges[captions[key]].add(i)
    payload = {"schema": 1, "nodes": nodes, "documents": documents,
               "edges": {str(k): sorted(v) for k, v in edges.items()}, "source_manifest": manifest}
    output.mkdir(parents=True, exist_ok=True)
    destination = output/"corpus.json"
    temp = output/"corpus.json.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    temp.replace(destination)
    stats = {"documents": len(documents), "pages": len(by_page), "blocks": len(nodes),
             "modalities": dict(counts), "images_resolved": sum(bool(n['image']) for n in nodes),
             "enriched_blocks": sum(bool(n['description']) for n in nodes),
             "edges": sum(map(len, edges.values())), "index_bytes": destination.stat().st_size,
             "build_seconds": round(time.perf_counter()-started, 4),
             "scope": "local structural index only; supplied parsing/description/vector construction excluded"}
    (output/"build_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), "utf-8")
    return stats


class Corpus:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        payload = json.loads(raw)
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        self.nodes = payload["nodes"]
        self.documents = payload["documents"]
        self.edges = {int(k): v for k, v in payload["edges"].items()}
        self.ids = {n["id"]: i for i, n in enumerate(self.nodes)}
        self.by_doc, self.by_page = collections.defaultdict(set), collections.defaultdict(set)
        for i,n in enumerate(self.nodes):
            self.by_doc[n["doc"]].add(i)
            self.by_page[(n["doc"], n["page"])].add(i)
        self.block_bm = BM25(self.search_text(n) for n in self.nodes)
        self.doc_names = list(self.documents)
        self.doc_bm = BM25(" ".join(self.search_text(self.nodes[i]) for i in sorted(self.by_doc[d])) for d in self.doc_names)

    @staticmethod
    def search_text(n):
        return f"{n['section']}\n{n['text']}\n{n['description']}"

    def neighbors(self, indices, limit=40):
        result, seen = [], set(indices)
        for i in indices:
            for j in self.edges.get(i, []):
                if j not in seen:
                    seen.add(j); result.append(j)
                    if len(result) >= limit:
                        return result
        return result
