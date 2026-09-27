"""Synthetic regression cases for evidence coverage and bounded model orchestration.

These tests never call a real model and do not measure benchmark answer accuracy.
"""
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from evidence_rag.agent import Agent, Evidence, clean_pages
from evidence_rag.index import Corpus, build
from evidence_rag.models import Config, ModelError, Models


class AgentV2(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "parsed" / "sample" / "auto"
        source.mkdir(parents=True)
        blocks = []
        for page in range(8):
            for block in range(4):
                blocks.append({"type": "text", "page_idx": page,
                               "text": f"Exchange report page {page+1} block {block}; value {100+page}."})
        (source / "sample_content_list.json").write_text(json.dumps(blocks), "utf-8")
        self.cfg = Config(parsed_root=str(self.root / "parsed"), pdf_root=str(self.root / "pdf"),
                          index_dir=str(self.root / "index"), use_vector=False, use_rerank=False,
                          use_planner=False, use_vision=False)
        build(self.cfg.parsed_root, self.cfg.index_dir)
        self.corpus = Corpus(self.root / "index" / "corpus.json")

    @staticmethod
    def answer(page, value=None):
        ident = f"sample:p{page}:b{(page-1)*4}"
        return {"sufficient": True, "answer": f"{value or 99+page} [{ident}]", "citations": [ident]}

    def test_packer_reserves_main_page_coverage(self):
        pages = [{"doc": "sample", "page": p} for p in range(1, 7)]
        # Block candidate list misses five pages entirely; page route still provides them.
        _, sources, stats = Evidence(self.cfg, self.corpus).pack(
            "exchange", list(range(4)), pages, time.monotonic()+30)
        self.assertEqual({source["page"] for source in sources.values()}, set(range(1, 7)))
        self.assertLessEqual(stats["text_chars"], self.cfg.context_chars)

    def test_model_page_request_is_resolved_and_pinned(self):
        self.cfg.evidence_blocks = 1
        replies = [{"sufficient": False, "read_pages": [{"doc": "sample", "page": 8}]},
                   self.answer(8), {"supported": True}]
        with patch.object(Models, "chat", side_effect=replies):
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["trace"][1]["directed_pages"], [{"doc": "sample", "page": 8}])
        self.assertIn("sample:p8:b28", result["trace"][1]["evidence_ids"])

    def test_missing_queries_does_not_prematurely_stop(self):
        self.cfg.evidence_blocks = 1
        replies = [{"sufficient": False}, self.answer(2), {"supported": True}]
        with patch.object(Models, "chat", side_effect=replies):
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["trace"]), 2)
        self.assertTrue(result["trace"][0]["fallback_pages"])

    def test_citation_format_repaired_using_same_evidence(self):
        candidate = self.answer(1)
        candidate["answer"] = "100"
        with patch.object(Models, "chat", side_effect=[candidate, self.answer(1), {"supported": True}]) as chat:
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(chat.call_count, 3)
        self.assertTrue(result["trace"][0]["same_evidence_repair"])
        self.assertEqual(chat.call_args_list[0].args[1], chat.call_args_list[1].args[1][:-1])

    def test_valid_json_with_wrong_boolean_schema_gets_one_repair(self):
        malformed = self.answer(1)
        malformed["sufficient"] = "true"
        with patch.object(Models, "chat", side_effect=[malformed, self.answer(1), {"supported": True}]) as chat:
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(chat.call_count, 3)

    def test_failed_verification_can_repair_without_an_unrelated_search(self):
        replies = [self.answer(1, 101), {"supported": False, "reason": "Wrong value: source says 100"},
                   self.answer(1), {"supported": True}]
        with patch.object(Models, "chat", side_effect=replies):
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["trace"]), 1)
        self.assertTrue(result["answer"].startswith("100 "))

    def test_repairs_are_bounded_and_bad_citations_remain_rejected(self):
        self.cfg.max_rounds = 1
        invalid = {"sufficient": True, "answer": "100 [unknown:p1:b0]", "citations": ["unknown:p1:b0"]}
        with patch.object(Models, "chat", return_value=invalid) as chat:
            result = Agent(self.cfg).answer("exchange report")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(result["citations"], [])

    def test_deterministic_arithmetic_failure_is_not_sent_to_a_lenient_verifier(self):
        self.cfg.max_rounds = 1
        candidate = self.answer(1)
        candidate["calculations"] = [{"expression": "101-100", "claimed_result": 100}]
        with patch.object(Models, "chat", return_value=candidate) as chat:
            result = Agent(self.cfg).answer("exchange change")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(chat.call_count, 1)
        self.assertFalse(result["trace"][0]["arithmetic_ok"])

    def test_multiple_queries_embed_once_and_rerank_once(self):
        self.cfg.use_planner = True
        self.cfg.use_rerank = True
        agent = Agent(self.cfg)
        agent.retriever.vdb = object()
        replies = [{"queries": ["exchange value", "report period"]}, self.answer(1), {"supported": True}]
        found = {"indices": list(range(8)), "routes": {"lexical": 8, "vector": 8}}
        with patch.object(Models, "chat", side_effect=replies), \
             patch.object(Models, "embed", return_value=[[1, 0]]*3) as embed, \
             patch.object(Models, "rerank", side_effect=lambda q, texts: list(range(len(texts)))) as rerank, \
             patch.object(agent.retriever, "search", return_value=found) as search:
            result = agent.answer("exchange report")
        self.assertEqual(result["status"], "verified")
        embed.assert_called_once_with(["exchange report", "exchange value", "report period"])
        self.assertEqual(rerank.call_count, 1)
        self.assertEqual(search.call_count, 3)
        self.assertTrue(all(call.kwargs["rerank"] is False and call.kwargs["query_vector"] == [1, 0]
                            for call in search.call_args_list))

    def test_page_requests_reject_unknown_pages_boolean_pages_and_unseen_documents(self):
        requests = [{"doc": "sample", "page": True}, {"doc": "sample", "page": 999},
                    {"doc": "../../private", "page": 1}, {"doc": "sample", "page": "2"},
                    {"doc": "sample", "page": 2}, {"doc": "sample", "page": 2}]
        self.assertEqual(clean_pages(requests, self.corpus, {"sample"}), [{"doc": "sample", "page": 2}])
        self.assertEqual(clean_pages(requests, self.corpus, {"other"}), [])

    def test_failed_page_render_is_not_repeated_and_text_evidence_survives(self):
        self.cfg.use_vision = True
        evidence = Evidence(self.cfg, self.corpus)
        with patch.object(evidence, "page_image", side_effect=ModelError("PDF page rendering failed")) as render:
            _, sources, stats = evidence.pack("exchange", [0], [{"doc": "sample", "page": 1}], time.monotonic()+30)
        self.assertIn("sample:p1:b0", sources)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(stats["images"], 0)
        self.assertTrue(stats["warnings"])

    def test_corrupt_page_image_does_not_drop_text_evidence(self):
        self.cfg.use_vision = True
        corrupt = self.root / "broken.jpg"
        corrupt.write_bytes(b"not an image")
        evidence = Evidence(self.cfg, self.corpus)
        with patch.object(evidence, "page_image", return_value=corrupt):
            _, sources, stats = evidence.pack("exchange", [0], [{"doc": "sample", "page": 1}], time.monotonic()+30)
        self.assertIn("sample:p1:b0", sources)
        self.assertEqual(stats["images"], 0)
        self.assertIn("full_page_image_invalid:sample:1", stats["warnings"])

    def test_explicit_page_read_expands_context_and_passes_followup_keywords(self):
        evidence = Evidence(self.cfg, self.corpus)
        page = {"doc": "sample", "page": 1}
        with patch.object(self.corpus, "focused_text", wraps=self.corpus.focused_text) as focus:
            _, sources, _ = evidence.pack("exchange", [0, 1, 2, 3], [page], time.monotonic()+30,
                                          focus_queries=["missing row keyword"], expanded_pages=[page])
        self.assertEqual(len(sources), 4)
        self.assertTrue(all("missing row keyword" in call.args[1] for call in focus.call_args_list))


class ModelV2(unittest.TestCase):
    @staticmethod
    def response(raw):
        return {"choices": [{"message": {"content": raw}, "finish_reason": "stop"}]}

    def test_json_repair_is_only_once_per_question(self):
        model = Models(Config())
        with patch.object(model, "post", side_effect=[self.response("broken"), self.response('{"ok":true}'),
                                                      self.response("also broken")]) as post:
            self.assertEqual(model.chat("Return JSON", "evidence"), {"ok": True})
            with self.assertRaises(ModelError):
                model.chat("Return JSON", "same evidence")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(model.format_repairs, 1)

    def test_hard_llm_call_budget(self):
        model = Models(Config(max_llm_calls=2))
        model.calls = [{"service": "llm"}, {"service": "llm"}]
        with patch.object(model, "post") as post:
            with self.assertRaisesRegex(ModelError, "budget"):
                model.chat("Return JSON", "evidence")
        post.assert_not_called()

    def test_failed_http_attempt_consumes_the_llm_budget(self):
        model = Models(Config(max_llm_calls=1))
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline synthetic test")) as request:
            with self.assertRaises(ModelError):
                model.chat("Return JSON", "evidence")
            with self.assertRaisesRegex(ModelError, "budget"):
                model.chat("Return JSON", "same evidence")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["service"], "llm")
        self.assertEqual(model.calls[0]["error"], "URLError")

    def test_rerank_uses_scores_if_endpoint_returns_input_order(self):
        model = Models(Config())
        with patch.object(model, "post", return_value={"results": [
            {"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9}]}):
            self.assertEqual(model.rerank("query", ["wrong", "right"]), [1, 0])

    def test_rerank_rejects_non_finite_scores(self):
        with patch.object(Models, "post", return_value={"results": [{"index": 0, "relevance_score": "NaN"}]}):
            with self.assertRaises(ModelError):
                Models(Config()).rerank("query", ["text"])


if __name__ == "__main__":
    unittest.main()
