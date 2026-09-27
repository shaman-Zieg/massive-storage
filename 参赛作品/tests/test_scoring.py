import ast
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_rag.evaluate import benchmark


class ScoringCompatibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.questions = self.root/"questions.json"
        self.questions.write_text(json.dumps([{"sample_id": "a", "question": "question", "answer": "secret label"}]), "utf-8")
        self.output = self.root/"output"

    def response(self, seconds=0.25):
        return io.BytesIO(json.dumps({"answer": "answer", "query_time_s": seconds,
                                      "status": "verified", "citations": []}).encode())

    def run_benchmark(self, **kwargs):
        with patch("evidence_rag.evaluate.urllib.request.urlopen", return_value=self.response()) as request:
            result = benchmark(self.questions, "http://localhost/query", self.output, **kwargs)
        self.assertEqual(json.loads(request.call_args.args[0].data), {"question": "question"})
        return result

    def read(self, name):
        return json.loads((self.output/name).read_text("utf-8"))

    def test_without_build_duration_answers_are_saved_but_scoring_is_not_ready(self):
        result = self.run_benchmark()
        self.assertFalse(result["official_scoring_ready"])
        self.assertNotIn("build_time", self.read("timings.json"))
        self.assertFalse(self.read("benchmark_manifest.json")["official_scoring_ready"])
        self.assertEqual(self.read("rag_answers.json")[0]["pred"], "answer")
        self.assertEqual(self.read("query_timings.json")[0]["query_time_s"], 0.25)

    def test_explicit_positive_build_time_produces_official_timing_keys(self):
        result = self.run_benchmark(build_time_s=123.5)
        self.assertTrue(result["official_scoring_ready"])
        timings = self.read("timings.json")
        self.assertEqual(timings["build_time"], 123.5)
        self.assertGreater(timings["search_time"], 0)
        self.assertEqual(timings["total_query_time_s"], 0.25)
        self.assertIn("whole sequential", self.read("benchmark_manifest.json")["search_time_boundary"].lower())

    def test_build_timing_file_imports_only_build_measurement(self):
        path = self.root/"build.json"
        path.write_text(json.dumps({"build_time": 432.1, "search_time": 999999}), "utf-8")
        self.run_benchmark(build_timings=path)
        timings = self.read("timings.json")
        self.assertEqual(timings["build_time"], 432.1)
        self.assertNotEqual(timings["search_time"], 999999)
        self.assertEqual(timings["build_time_source"], str(path.resolve()))

    def test_invalid_build_times_rejected_before_any_http_request(self):
        for value in (0, -1, float("nan"), float("inf"), float("-inf"), True, "5"):
            with self.subTest(value=value), patch("evidence_rag.evaluate.urllib.request.urlopen") as request:
                with self.assertRaises(ValueError):
                    benchmark(self.questions, "http://localhost/query", self.output, build_time_s=value)
                request.assert_not_called()
        with self.assertRaises(ValueError):
            benchmark(self.questions, "http://localhost/query", self.output, build_time_s=1, build_timings="ignored.json")
        path = self.root/"invalid.json"
        for value in ({}, {"build_time": 0}, {"build_time": float("nan")}):
            path.write_text(json.dumps(value), "utf-8")
            with self.assertRaises(ValueError):
                benchmark(self.questions, "http://localhost/query", self.output, build_timings=path)

    def test_invalid_server_timing_invalidates_old_scoring_manifest(self):
        self.run_benchmark(build_time_s=1)
        for value in (0, float("nan"), float("inf")):
            with self.subTest(value=value), patch("evidence_rag.evaluate.urllib.request.urlopen", return_value=self.response(value)):
                with self.assertRaises(ValueError):
                    benchmark(self.questions, "http://localhost/query", self.output, build_time_s=1)
            self.assertFalse(self.read("benchmark_manifest.json")["official_scoring_ready"])
            self.assertFalse(self.read("timings.json")["official_scoring_ready"])
            self.assertNotIn("search_time", self.read("timings.json"))

    def test_cli_forwards_build_timing_options(self):
        from evidence_rag.__main__ import main
        from evidence_rag.models import Config
        for option, value, key in (("--build-time-s", "123.5", "build_time_s"),
                                   ("--build-timings", "build.json", "build_timings")):
            args = ["evidence_rag", "benchmark", "--questions", str(self.questions), "--output", str(self.output), option, value]
            with patch("sys.argv", args), patch("evidence_rag.__main__.Config.load", return_value=Config()), \
                 patch("evidence_rag.evaluate.benchmark", return_value={}) as run, patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(), 0)
                self.assertEqual(run.call_args.kwargs[key], float(value) if key == "build_time_s" else value)

    def test_partial_http_failure_preserves_completed_answers_but_never_ready(self):
        from urllib.error import URLError
        self.run_benchmark(build_time_s=1)
        self.questions.write_text(json.dumps([{"sample_id": "a", "question": "first"},
                                              {"sample_id": "b", "question": "second"}]), "utf-8")
        with patch("evidence_rag.evaluate.urllib.request.urlopen", side_effect=[self.response(), URLError("interrupted")]):
            with self.assertRaises(URLError):
                benchmark(self.questions, "http://localhost/query", self.output, build_time_s=1)
        self.assertEqual(len(self.read("rag_answers.json")), 1)
        self.assertEqual(len(self.read("query_timings.json")), 1)
        self.assertFalse(self.read("benchmark_manifest.json")["official_scoring_ready"])
        self.assertFalse(self.read("benchmark_manifest.json")["complete"])
        self.assertFalse(self.read("timings.json")["official_scoring_ready"])
        self.assertNotIn("search_time", self.read("timings.json"))

    def test_unchanged_official_loader_accepts_generated_file_when_available(self):
        official = (Path(__file__).resolve().parents[2]/"索引与demo代码-0730"/"RAG-Anything-0713"/
                    "rag-anything-experiments"/"rag_scripts"/"calculate_final_score.py")
        if not official.is_file():
            self.skipTest("Official demo source is outside the distributed submission")
        # Execute the exact official loader in isolation, avoiding module-level
        # dotenv loading that could overwrite the developer's environment.
        tree = ast.parse(official.read_text("utf-8"))
        loader = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "load_timings")
        namespace = {"json": json, "os": os}
        exec(compile(ast.Module(body=[loader], type_ignores=[]), str(official), "exec"), namespace)
        self.run_benchmark(build_time_s=456)
        build_time, search_time = namespace["load_timings"](self.output/"timings.json")
        self.assertEqual(build_time, 456)
        self.assertGreater(search_time, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
