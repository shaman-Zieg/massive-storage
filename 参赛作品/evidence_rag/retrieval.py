"""BM25, NanoVectorDB and document-layout graph retrieval with RRF fusion."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from .index import Corpus
from .models import ModelError


class Retriever:
    def __init__(self, config, offline=False):
        self.cfg, self.offline = config, offline
        self.corpus = Corpus(Path(config.index_dir)/"corpus.json")
        self.vdb = None
        self.native_vectors = False
        if config.use_vector and not offline:
            try:
                from nano_vectordb import NanoVectorDB
            except ImportError as exc:
                raise ModelError("Install nano-vectordb; competition mode cannot silently drop vector search") from exc
            native = Path(config.index_dir)/"vectors.json"
            if native.exists():
                metadata = json.loads((Path(config.index_dir)/"vector_manifest.json").read_text("utf-8"))
                if metadata != {"corpus_sha256": self.corpus.fingerprint, "embedding_model": config.embedding_model,
                               "embedding_dim": config.embedding_dim}:
                    raise ModelError("Vector index does not match corpus/model; rebuild vectors")
                self.native_vectors = True
            else:
                native = Path(config.legacy_storage)/"vdb_chunks.json"
            if not native.is_file():
                raise ModelError("No vector index; run embed or configure supplied legacy index")
            self.vdb = NanoVectorDB(config.embedding_dim, storage_file=str(native))

    def search(self, question, models=None, k=None, *, query_vector=None, rerank=True):
        c, cfg = self.corpus, self.cfg
        k = k or cfg.candidates
        routes = {"lexical": [i for i,_ in c.block_bm.search(question, k)]}
        docs = [c.doc_names[i] for i,_ in c.doc_bm.search(question, 4)]
        doc_route = []
        per_doc = [c.block_bm.search(question, 16, c.by_doc[d]) for d in docs]
        # Interleaving keeps a second plausible document in the candidate pool.
        for rank in range(16):
            for hits in per_doc:
                if rank < len(hits):
                    doc_route.append(hits[rank][0])
        routes["document"] = doc_route
        if cfg.use_page_index:
            page_hits = c.page_bm.search(question, 20)
            # Return page-local blocks with provenance; do not manufacture page
            # text as a citeable block or borrow labels from the evaluation set.
            page_lists = [c.block_bm.search(question, 3, c.by_page[c.page_keys[p]]) for p,_ in page_hits]
            routes['page'] = [hits[r][0] for r in range(3) for hits in page_lists if r<len(hits)]
        if cfg.use_table_rows:
            row_hits = c.table_bm.search(question, 80)
            routes['table'] = list(dict.fromkeys(c.table_parents[i] for i,_ in row_hits))[:20]
        if self.vdb is not None:
            if query_vector is None:
                query_vector = models.embed([question])[0]
            hits = self.vdb.query(query_vector, top_k=40)
            if self.native_vectors:
                routes["vector"] = [c.ids[h["__id__"]] for h in hits if h["__id__"] in c.ids]
            else:
                # Legacy chunk page alignment is uncertain: use it only to select documents.
                # Final evidence and citations always come from exact MinerU page identifiers.
                vector_docs = list(dict.fromkeys(Path(h.get("file_path", "").replace("\\", "/")).stem for h in hits))
                vector_lists = [c.block_bm.search(question, 12, c.by_doc[d]) for d in vector_docs[:6] if d in c.by_doc]
                routes["vector"] = [ls[r][0] for r in range(12) for ls in vector_lists if r < len(ls)]
        # Page and row windows add recall candidates; repeated descriptions or
        # generic table headers must not multiply a block's primary RRF score.
        primary = {key:value for key,value in routes.items() if key not in ('page','table')}
        fused = self.fuse(primary)
        if cfg.use_graph:
            routes["graph"] = c.neighbors([i for i,_ in fused[:12]], 40)
            primary['graph'] = routes['graph']
            fused = self.fuse(primary)
        base = [i for i,_ in fused]
        extra_routes = [routes.get('page',[])[:12],routes.get('table',[])[:8]]
        supplements = list(dict.fromkeys(route[r] for r in range(12) for route in extra_routes if r<len(route)))
        reserve = min(len(supplements), max(1,k//5)) if supplements else 0
        candidates = list(dict.fromkeys(base[:k-reserve]+supplements+base))[:k]
        if rerank and not self.offline and cfg.use_rerank and candidates:
            order = models.rerank(question, [self.rerank_text(i,question) for i in candidates])
            candidates = [candidates[i] for i in order]
        return {"indices": candidates, "routes": {key: len(val) for key,val in routes.items()},
                "pages": self.rank_pages(candidates, question)}

    @staticmethod
    def fuse(routes):
        weights = {"lexical": 1.0, "document": 0.65, "vector": 1.0, "graph": 0.35,
                   'page':0.65,'table':0.5}
        scores = collections.defaultdict(float)
        for route, indices in routes.items():
            for rank,i in enumerate(dict.fromkeys(indices)):
                scores[i] += weights[route]/(60+rank+1)
        return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))

    def rerank_text(self,index,question):
        node=self.corpus.nodes[index]
        text=self.corpus.focused_text(index,question,4500) if self.cfg.use_table_rows else node['text'][:4500]
        return (node['section']+'\n'+text+'\nSecondary description:\n'+node['description'][:1200])[:6000]

    def rank_pages(self, candidates, question=None):
        scores = collections.defaultdict(list)
        for rank,i in enumerate(candidates):
            node = self.corpus.nodes[i]
            scores[(node["doc"], node["page"])].append(1/(10+rank))
        # Best hit dominates; up to three supporting blocks provide a bounded bonus.
        result = sorted(scores, key=lambda key: (-(max(scores[key])+0.2*sum(sorted(scores[key], reverse=True)[:3])), key))
        if question and self.cfg.use_page_index:
            page_hits = [self.corpus.page_keys[i] for i,_ in self.corpus.page_bm.search(question,30)]
            fused = collections.defaultdict(float)
            # Live neural order has more influence; offline diagnostics cannot
            # establish the benefit of this online-only setting.
            block_weight = 2 if not self.offline and self.cfg.use_rerank else 1
            for route,weight in ((result,block_weight),(page_hits,1)):
                for rank,key in enumerate(route):
                    fused[key] += weight/(60+rank+1)
            result = sorted(fused,key=lambda key:(-fused[key],key))
            # Reserve at most two secondary context pages beside the leading
            # source. Four relevant pages stay ahead of continuity context, and
            # cross-document hits remain reachable. No QA labels are consulted.
            if result and self.cfg.use_page_neighbors:
                doc,page = result[0]
                neighbors = [(doc,p) for p in (page-1,page+1) if (doc,p) in self.corpus.by_page]
                result = list(dict.fromkeys(result[:4]+neighbors+result[4:]))
        return [{"doc": d, "page": p} for d,p in result]


def embed_corpus(config, models, batch_size=16):
    from nano_vectordb import NanoVectorDB
    corpus = Corpus(Path(config.index_dir)/"corpus.json")
    path = Path(config.index_dir)/"vectors.building.json"
    metadata = {"corpus_sha256": corpus.fingerprint, "embedding_model": config.embedding_model,
                "embedding_dim": config.embedding_dim}
    checkpoint = Path(config.index_dir)/"vectors.building.manifest.json"
    if path.exists() and (not checkpoint.exists() or json.loads(checkpoint.read_text("utf-8")) != metadata):
        raise ModelError("Partial vector build belongs to different corpus/model; move it aside before retry")
    checkpoint.write_text(json.dumps(metadata), "utf-8")
    db = NanoVectorDB(config.embedding_dim, storage_file=str(path))
    todo = [node for node in corpus.nodes if not db.get([node['id']])]
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start+batch_size]
        vectors = models.embed([corpus.search_text(n)[:6000] for n in batch])
        db.upsert([{"__id__": n["id"], "__vector__": v} for n,v in zip(batch, vectors)])
        db.save()
        print(f"embedded {min(start+batch_size,len(todo))}/{len(todo)}", flush=True)
    if not path.exists():
        db.save()
    path.replace(Path(config.index_dir)/"vectors.json")
    (Path(config.index_dir)/"vector_manifest.json").write_text(json.dumps(metadata), "utf-8")
    return {"vectors": len(corpus.nodes), "embedding_model": config.embedding_model}
