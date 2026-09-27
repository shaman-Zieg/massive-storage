import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evidence_rag.evaluate import document_bootstrap, document_split, paired_comparison, retrieval_report
from evidence_rag.index import build
from evidence_rag.models import Config


def row(ident, docs, score=1):
    return {"sample_id": ident, "question": "question "+ident,
            "expected_pages": [[doc, 1] for doc in docs], "hit@3": score,
            "all_pages@3": score, "page_recall@3": score}


class EvaluationStatistics(unittest.TestCase):
    def test_split_is_deterministic_order_independent_and_document_disjoint(self):
        rows = [row("a", ["d1", "d2"]), row("b", ["d2", "d3"]),
                row("c", ["d4"]), row("d", ["d5"]), row("e", ["d6"])]
        split = document_split(rows, seed=5)
        self.assertEqual(split, document_split(list(reversed(rows)), seed=5))
        self.assertFalse(set(split["dev"]["documents"]) & set(split["holdout"]["documents"]))
        self.assertEqual(split["document_groups"], 4)
        for partition in ("dev", "holdout"):
            ids = split[partition]["sample_ids"]
            self.assertEqual("a" in ids, "b" in ids)
        self.assertIn("NOT a blind", split["label_exposure"])

    def test_single_document_cannot_provide_independent_holdout(self):
        split = document_split([row("a", ["same"]), row("b", ["same"])])
        self.assertEqual(split["holdout"]["count"], 0)
        self.assertIn("warning", split)
        self.assertEqual(document_split([])["dev"]["count"], 0)
        with self.assertRaises(ValueError):
            document_split([], holdout_fraction=1)

    def test_cluster_bootstrap_is_reproducible_and_preserves_perfect_score(self):
        rows = [row(str(i), ["document "+str(i//2)]) for i in range(12)]
        first = document_bootstrap(rows, seed=42, iterations=100)
        self.assertEqual(first, document_bootstrap(rows, seed=42, iterations=100))
        self.assertEqual(first["hit@3"]["low"], 1)
        self.assertEqual(first["hit@3"]["high"], 1)
        self.assertEqual(first["hit@3"]["document_groups"], 6)
        self.assertEqual(document_bootstrap([], iterations=100), {})

    def test_paired_comparison_aligns_ids_not_input_positions(self):
        before = {"details": [row("a", ["d1"], 0), row("b", ["d2"], 1), row("c", ["d3"], 0)]}
        after = {"details": [row("c", ["d3"], 0), row("b", ["d2"], 0), row("a", ["d1"], 1)]}
        comparison = paired_comparison(before, after, iterations=100)
        metric = comparison["metrics"]["hit@3"]
        self.assertEqual(comparison["matched_samples"], 3)
        self.assertEqual((metric["improved"], metric["regressed"], metric["unchanged"]), (1, 1, 1))
        self.assertEqual(metric["delta"], 0)
        self.assertLessEqual(metric["delta_ci95"]["low"], 0)
        self.assertGreaterEqual(metric["delta_ci95"]["high"], 0)

    def test_paired_comparison_validates_labels_questions_and_duplicate_ids(self):
        original = {"details": [row("a", ["d1"])]}
        for changed in (row("a", ["d2"]), {**row("a", ["d1"]), "question": "changed"}):
            with self.assertRaises(ValueError):
                paired_comparison(original, {"details": [changed]}, iterations=100)
        with self.assertRaises(ValueError):
            paired_comparison(original, {"details": [row("a", ["d1"]), row("a", ["d1"])]}, iterations=100)
        with self.assertRaises(ValueError):
            paired_comparison(original, {"details": [{**row("a", ["d1"]), "sample_id": None}]}, iterations=100)

    def test_old_report_path_recovers_six_pages_without_inventing_packed_metrics(self):
        pages = [["irrelevant", i] for i in range(1, 6)] + [["d1", 1]]
        old = {"details": [{**row("a", ["d1"], 0), "retrieved_pages": pages}, row("old", ["old_doc"])]}
        new = {"details": [{**row("a", ["d1"], 1), "retrieved_pages": [["d1", 1]],
                            "packed_text_hit": 1, "packed_text_all_pages": 1, "packed_text_page_recall": 1}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"old.json"
            path.write_text(json.dumps(old), "utf-8")
            comparison = paired_comparison(path, new, iterations=100)
        self.assertEqual(comparison["metrics"]["hit@6"]["baseline"], 1)
        self.assertEqual(comparison["baseline_only_ids"], ["old"])
        self.assertIn("packed_text_hit", comparison["metrics_not_comparable"])
        self.assertNotIn("packed_text_hit", comparison["metrics"])
        self.assertNotIn("hit@6", old["details"][0])


class RetrievalReportContract(unittest.TestCase):
    def test_labels_do_not_enter_search_or_evidence_pack_and_metrics_distinguish_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            config = Config(parsed_root=str(path), pdf_root=str(path), index_dir=str(path),
                            use_vision=True, context_chars=400, evidence_blocks=2)
            corpus = SimpleNamespace(by_page={("finance_1", 1): [], ("finance_1", 2): []}, fingerprint="test")
            calls = []

            class Search:
                def __init__(self, received_config, offline):
                    self.corpus = corpus
                    self.assert_offline = offline

                def search(self, question):
                    calls.append(("search", question))
                    return {"indices": [7, 9], "pages": [{"doc": "finance_1", "page": 1}, {"doc": "finance_1", "page": 2}]}

            class Pack:
                def __init__(self, received_config, received_corpus):
                    self.cfg = received_config

                def pack(self, question, indices, pages, deadline):
                    calls.append(("pack", question, indices, pages, self.cfg.use_vision))
                    return [], {"source": {"doc": "finance_1", "page": 2}}, {"text_chars": 100, "images": 0, "warnings": []}

            questions = [{"question": "question only", "sample_id": "1", "domain": "finance", "answer_type": "table",
                          "answer": "SECRET LABEL MUST NOT BE PASSED",
                          "gt_image_paths": ["images/finance/1/1_page_0001.png"]}]
            questions_path = path/"questions.json"
            questions_path.write_text(json.dumps(questions), "utf-8")
            with patch("evidence_rag.evaluate.Retriever", Search), patch("evidence_rag.evaluate.Evidence", Pack):
                summary = retrieval_report(config, questions_path, path/"report.json", bootstrap_iterations=100)
            report = json.loads((path/"report.json").read_text("utf-8"))
            self.assertEqual(report["overall"]["hit@3"], 1)
            self.assertEqual(report["overall"]["packed_text_hit"], 0)
            self.assertEqual(report["candidate_page_budgets"]["6"]["all_pages"], 1)
            self.assertIsNone(report["answer_accuracy"])
            self.assertIn("finance", report["by_domain"])
            self.assertIn("finance_1", report["by_document"])
            self.assertNotIn("details", summary)
            self.assertEqual(report["use_page_index"], config.use_page_index)
            self.assertEqual(report["use_table_rows"], config.use_table_rows)
            self.assertEqual(report["use_graph"], config.use_graph)
            detail = report["details"][0]
            self.assertEqual(detail["retrieval_and_packing_seconds"], detail["seconds"]+detail["packing_seconds"])
            self.assertEqual(report["mean_packing_seconds"], report["p95_packing_seconds"])
            self.assertEqual(report["mean_retrieval_and_packing_seconds"], report["p95_retrieval_and_packing_seconds"])
            self.assertIn("NOT official query_time_s", report["timing_protocol"]["scope"])
            self.assertTrue(config.use_vision)  # Evaluation must not mutate deployment configuration.
            self.assertNotIn("SECRET", repr(calls))
            self.assertEqual(calls[0], ("search", "question only"))
            self.assertEqual(calls[1][1:3], ("question only", [7, 9]))
            self.assertFalse(calls[1][-1])

    def test_real_packer_obeys_small_context_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            source = path/"parsed"/"finance_1"/"auto"
            source.mkdir(parents=True)
            blocks = [{"type": "text", "text": "Exchange rate Nigeria 167.9", "page_idx": 0},
                      {"type": "table", "table_caption": ["Exchange rate table"],
                       "table_body": "<table><tr><td>167.9</td></tr></table>", "page_idx": 1}]
            (source/"finance_1_content_list.json").write_text(json.dumps(blocks), "utf-8")
            config = Config(parsed_root=str(path/"parsed"), pdf_root=str(path/"pdf"), index_dir=str(path/"index"),
                            use_vector=False, use_rerank=False, use_vision=True, context_chars=80)
            build(config.parsed_root, config.index_dir)
            sample = {"sample_id": "test", "question": "Nigeria exchange rate", "domain": "finance", "answer_type": "text_only",
                      "gt_image_paths": ["images/finance/1/1_page_0001.png"]}
            questions = path/"questions.json"
            questions.write_text(json.dumps([sample]), "utf-8")
            summary = retrieval_report(config, questions, path/"report.json", bootstrap_iterations=100)
            self.assertEqual(summary["overall"]["hit@3"], 1)
            self.assertEqual(summary["overall"]["packed_text_hit"], 0)
            self.assertEqual(summary["evidence_protocol"]["context_chars"], 80)


if __name__ == "__main__":
    unittest.main(verbosity=2)
