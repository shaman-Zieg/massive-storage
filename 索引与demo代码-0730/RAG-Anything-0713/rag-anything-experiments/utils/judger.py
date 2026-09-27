#!/usr/bin/env python3
import os
import json
import time
import argparse
from collections import defaultdict

from openai import OpenAI
from tqdm import tqdm
from dotenv import load_dotenv
import sys


STRICT_PROMPT = """You are a strict evaluator for question answering.

Your task:
Given a question, a ground-truth answer, and a model prediction, determine whether the prediction should be considered correct.

Evaluation rules:
1. Output 1 if the prediction is semantically correct and answers the question.
2. Output 0 if the prediction is wrong, incomplete in a way that misses key information, irrelevant, or empty.
3. Ignore minor wording differences, paraphrases, or formatting differences.
4. Be strict about factual correctness.
5. If the prediction contains extra unsupported claims that change the meaning, output 0.
6. Only output a JSON object, with no extra text.

Return format:
{"score": 1, "reason": "brief reason"}

"""

RELAXED_PROMPT = """You are a evaluator for question answering.

Your task:
Given a question, a ground-truth answer, and a model prediction, determine whether the prediction should be considered correct.

Evaluation rules:
1. Output 1 if the prediction is semantically correct and answers the question.
2. Output 0 if the prediction is wrong, incomplete in a way that misses key information, irrelevant, or empty.
3. Ignore minor wording differences, paraphrases, or formatting differences.
4. Be strict about factual correctness.
5. The model prediction may contains extra information beyond ground-truth answer, which is expected as it is based on RAG. The full mark should be given as long as the extra information does not contradict the meaning.
6. Only output a JSON object, with no extra text.

Return format:
{"score": 1, "reason": "brief reason"}

"""

JUDGE_PROMPT = RELAXED_PROMPT
dotenv_file = os.getenv('DOTENV_FILE', '.env')

load_dotenv(dotenv_path=dotenv_file, override=True)
LLM_BINDING_HOST = os.getenv("LLM_BINDING_HOST", "http://localhost:8000")
def make_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url)


def judge_one_sample(client: OpenAI, model_name: str, question: str, gt_answer: str, pred_answer: str,
                     max_tokens: int = 256, temperature: float = 0.0, max_try: int = 3):
    user_content = f"""Question:
    {question}

    Ground Truth Answer:
    {gt_answer}

    Model Prediction:
    {pred_answer}
    """

    last_err = None
    for _ in range(max_try):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": JUDGE_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            text = completion.choices[0].message.content.strip()
            result = json.loads(text)
            score = int(result.get("score", 0))
            reason = result.get("reason", "")
            score = 1 if score == 1 else 0
            return score, reason
        except Exception as e:
            last_err = str(e)
            time.sleep(1)

    return 0, f"judge_error: {last_err}"


def compute_metrics(samples):
    total = len(samples)
    correct = sum(int(x.get("score", 0)) for x in samples)
    accuracy = correct / total if total > 0 else 0.0

    # 在你这个“每题只有一个标准答案、判对=1”的设定下，recall 数值等同于 accuracy
    recall = accuracy
    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "recall": recall,
    }


def compute_group_metrics(samples, group_key):
    grouped = defaultdict(list)
    for s in samples:
        key = s.get(group_key, "UNKNOWN")
        grouped[key].append(s)

    stats = {}
    for key, group in grouped.items():
        stats[key] = compute_metrics(group)
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_path", type=str, default=os.getenv("BENCHMARK_NAME", "") + "_results" + "/" + "rag_answers.json")
    parser.add_argument("--output_path", type=str, default=os.getenv("BENCHMARK_NAME", "") + "_results" + "/" + "rag_answers_judged.json", help="Path to save judged JSON")
    parser.add_argument("--judge_model", type=str, default=os.getenv("JUDGER_MODEL", ""))
    parser.add_argument("--api_key", type=str, default=os.getenv("JUDGER_API_KEY", ""))
    parser.add_argument("--base_url", type=str, default=os.getenv("JUDGER_BINDING_HOST", ""))
    parser.add_argument("--max_tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_try", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("Please provide --api_key or set DASHSCOPE_API_KEY")

    if args.output_path is None:
        if args.input_path.endswith(".json"):
            args.output_path = args.input_path[:-5] + "_judged.json"
        else:
            args.output_path = args.input_path + "_judged.json"

    client = make_client(args.api_key, args.base_url)
    # client = OpenAI(api_key=api_key, base_url=LLM_BINDING_HOST)

    with open(args.input_path, "r", encoding="utf-8") as f:
        samples = json.load(f)

    if not isinstance(samples, list):
        raise TypeError("Input JSON must be a list")

    existing = {}
    if args.resume and os.path.exists(args.output_path):
        with open(args.output_path, "r", encoding="utf-8") as f:
            old_samples = json.load(f)
        for s in old_samples:
            key = (s.get("question", ""), s.get("answer", ""), s.get("pred", ""))
            if "score" in s:
                existing[key] = s

    judged_samples = []
    start_time = time.time()

    for idx, sample in enumerate(tqdm(samples, desc="Judging")):
        question = sample.get("question", "")
        gt_answer = sample.get("answer", "")
        pred_answer = sample.get("pred", "")

        key = (question, gt_answer, pred_answer)

        if args.resume and key in existing:
            judged_sample = dict(sample)
            for field in ("score", "judge_reason", "judge_time"):
                if field in existing[key]:
                    judged_sample[field] = existing[key][field]
            judged_samples.append(judged_sample)
            continue

        judged_sample = dict(sample)

        if not pred_answer or str(pred_answer).strip() == "":
            judged_sample["score"] = 0
            judged_sample["judge_reason"] = "empty prediction"
        else:
            judge_start = time.time()
            score, reason = judge_one_sample(
                client=client,
                model_name=args.judge_model,
                question=question,
                gt_answer=gt_answer,
                pred_answer=pred_answer,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                max_try=args.max_try,
            )
            judge_time = time.time() - judge_start

            judged_sample["score"] = score
            judged_sample["judge_reason"] = reason
            judged_sample["judge_time"] = round(judge_time, 4)

        judged_samples.append(judged_sample)

        metrics = compute_metrics(judged_samples)

        print("-" * 80)
        print(f"[{idx+1}/{len(samples)}]")
        print(f"Question   : {question}")
        print(f"GT Answer  : {gt_answer}")
        print(f"Prediction : {pred_answer}")
        print(f"Score      : {judged_sample.get('score', 0)}")
        print(f"Reason     : {judged_sample.get('judge_reason', '')}")
        print(f"Running Acc: {metrics['accuracy']:.4f}")
        print(f"Running Rec: {metrics['recall']:.4f}")

        with open(args.output_path, "w", encoding="utf-8") as f:
            json.dump(judged_samples, f, ensure_ascii=False, indent=2)

    total_time = time.time() - start_time

    final_metrics = compute_metrics(judged_samples)
    by_domain = compute_group_metrics(judged_samples, "domain")
    by_answer_type = compute_group_metrics(judged_samples, "answer_type")

    summary = {
        "overall": final_metrics,
        "by_domain": by_domain,
        "by_answer_type": by_answer_type,
        "elapsed_time_sec": round(total_time, 4),
    }

    summary_path = args.output_path.replace(".json", "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print("Final Results")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 80)
    print(f"Judged results saved to : {args.output_path}")
    print(f"Summary saved to        : {summary_path}")


if __name__ == "__main__":
    main()
