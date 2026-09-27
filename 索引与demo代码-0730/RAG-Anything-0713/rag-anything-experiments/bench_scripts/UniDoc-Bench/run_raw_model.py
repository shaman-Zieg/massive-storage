#!/usr/bin/env python3
import argparse
import base64
import io
import json
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests
from PIL import Image
from tqdm import tqdm
from dotenv import load_dotenv
import os

dotenv_file = os.getenv('DOTENV_FILE', '.env')

load_dotenv(dotenv_path=dotenv_file, override=True)
def image_path_to_pdf_path(gt_image_path: str, pdf_root: Path) -> Path:
    """
    Example:
      images/commerce_manufacturing/3274043/3274043_page_0006.png
    ->
      documents/sampled_documents/commerce_manufacturing_3274043.pdf
    """
    parts = Path(gt_image_path).parts
    if len(parts) < 4:
        raise ValueError(f"Invalid gt_image_path: {gt_image_path}")

    domain = parts[1]
    doc_id = parts[2]
    pdf_name = f"{domain}_{doc_id}.pdf"
    return pdf_root / pdf_name


def render_pdf_to_base64_images(
    pdf_path: Path,
    dpi: int = 144,
    max_pages: int | None = None,
    jpeg_quality: int = 85,
) -> list[str]:
    doc = fitz.open(pdf_path)
    images_b64 = []

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    page_count = len(doc) if max_pages is None else min(len(doc), max_pages)

    for page_idx in range(page_count):
        page = doc.load_page(page_idx)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality)
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        images_b64.append(img_b64)

    doc.close()
    return images_b64


def chunk_list(items: list, chunk_size: int) -> list[list]:
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def build_chunk_messages(question: str, page_images_b64: list[str], chunk_idx: int, total_chunks: int):
    text_prompt = (
        f"You are answering a question based on a chunk of document pages.\n"
        f"This is chunk {chunk_idx + 1} of {total_chunks}.\n"
        f"Use only the information visible in these pages.\n"
        f"If the answer is not fully contained in this chunk, provide any relevant partial evidence.\n\n"
        f"Question: {question}\n\n"
        f"Return a concise answer or partial evidence from this chunk."
    )

    content = [{"type": "text", "text": text_prompt}]
    for img_b64 in page_images_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                },
            }
        )

    return [{"role": "user", "content": content}]


def build_summary_messages(question: str, chunk_preds: list[dict]):
    evidence_lines = []
    for item in chunk_preds:
        evidence_lines.append(
            f"Chunk {item['chunk_id']} (pages {item['page_start']}-{item['page_end']}):\n{item['pred']}"
        )

    evidence_text = "\n\n".join(evidence_lines)

    text_prompt = (
        "You are given answers or partial evidence extracted from multiple chunks of the same document.\n"
        "Synthesize them into one final answer to the question.\n"
        "Use the evidence faithfully, avoid adding unsupported details, and keep the answer concise.\n\n"
        f"Question: {question}\n\n"
        f"Chunk evidence:\n{evidence_text}\n\n"
        "Final answer:"
    )

    return [{"role": "user", "content": text_prompt}]


def call_vllm_chat(
    api_url: str,
    model_name: str,
    messages,
    timeout: int = 300,
    temperature: float = 0.0,
    max_tokens: int = 512,
    api_key: str = "1234"
) -> str:
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(
        api_url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=timeout,
    )

    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:2000]}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {sec:.2f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {sec:.2f}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", help="Input QA json file", default=os.getenv("BENCH_QUERIES", ""))
    parser.add_argument("--bench_name", type=str, default=os.getenv("BENCHMARK_NAME", "UniDoc-Bench"))
    parser.add_argument(
        "--pdf_root",
        default=os.getenv("UNIDOCBENCH_DATASET_PATH", ""), 
        help="Root directory of sampled PDFs",
    )
    parser.add_argument(
        "--output_json",
        default=os.getenv("BENCHMARK_NAME", "") + "_results" + "/" + "raw_model_answers.json", 
        help="Output json path",
    )
    parser.add_argument("--output_path", type=str, default=os.getenv("BENCHMARK_NAME", "") + "_results" + "/" + "raw_model_answers.json")
    parser.add_argument(
        "--api_url",
        default=os.getenv("VLLM_BINDING_HOST", "") + "/chat/completions",
        help="OpenAI-compatible vLLM endpoint",
    )
    parser.add_argument(
        "--model_name",
        default=os.getenv("VLLM_MODEL", ""),
        help="Model name",
    )
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--max_pages", type=int, default=None)
    parser.add_argument("--chunk_size", type=int, default=4, help="Pages per chunk, e.g. 4 or 8")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_tokens", type=int, default=512)
    parser.add_argument("--summary_max_tokens", type=int, default=512)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print("Output: " + args.output_json)
    input_json = Path(args.input_json).resolve()
    pdf_root = Path(args.pdf_root).resolve()
    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)

    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise TypeError("Input JSON must be a list of QA items.")

    existing_done = {}
    if args.resume and output_json.exists():
        with open(output_json, "r", encoding="utf-8") as f:
            existing = json.load(f)
        for item in existing:
            q = item.get("question", "")
            gt_paths = tuple(item.get("gt_image_paths", []))
            if item.get("pred"):
                existing_done[(q, gt_paths)] = item

    results = []
    total_start = time.time()

    for idx, item in enumerate(tqdm(data, desc="Running chunked VLM inference", unit="sample"), start=1):
        question = item.get("question", "")
        gt_paths = item.get("gt_image_paths", [])
        key = (question, tuple(gt_paths))

        if args.resume and key in existing_done:
            results.append(existing_done[key])
            continue

        new_item = dict(item)

        try:
            if not gt_paths:
                raise ValueError("gt_image_paths is empty")

            pdf_path = image_path_to_pdf_path(gt_paths[0], pdf_root)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF not found: {pdf_path}")

            render_start = time.time()
            page_images_b64 = render_pdf_to_base64_images(
                pdf_path=pdf_path,
                dpi=args.dpi,
                max_pages=args.max_pages,
            )
            pdf_render_time = time.time() - render_start

            image_chunks = chunk_list(page_images_b64, args.chunk_size)
            total_chunks = len(image_chunks)

            chunk_preds = []
            chunk_pred_time_total = 0.0

            for chunk_idx, img_chunk in enumerate(image_chunks):
                messages = build_chunk_messages(
                    question=question,
                    page_images_b64=img_chunk,
                    chunk_idx=chunk_idx,
                    total_chunks=total_chunks,
                )

                pred_start = time.time()
                chunk_pred = call_vllm_chat(
                    api_url=args.api_url,
                    model_name=args.model_name,
                    messages=messages,
                    timeout=args.timeout,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    api_key=os.getenv('VLLM_BINDING_API_KEY', '1234')
                )
                chunk_pred_time = time.time() - pred_start
                chunk_pred_time_total += chunk_pred_time

                page_start = chunk_idx * args.chunk_size + 1
                page_end = min((chunk_idx + 1) * args.chunk_size, len(page_images_b64))

                chunk_preds.append(
                    {
                        "chunk_id": chunk_idx + 1,
                        "page_start": page_start,
                        "page_end": page_end,
                        "pred": chunk_pred,
                        "pred_time": round(chunk_pred_time, 4),
                    }
                )

            summary_messages = build_summary_messages(question, chunk_preds)

            summary_start = time.time()
            final_pred = call_vllm_chat(
                api_url=args.api_url,
                model_name=args.model_name,
                messages=summary_messages,
                timeout=args.timeout,
                temperature=args.temperature,
                max_tokens=args.summary_max_tokens,
                api_key=os.getenv('VLLM_BINDING_API_KEY', '1234')
            )
            summary_pred_time = time.time() - summary_start

            total_pred_time = chunk_pred_time_total + summary_pred_time

            new_item["pred"] = final_pred
            new_item["chunk_preds"] = chunk_preds
            new_item["pdf_path"] = str(pdf_path)
            new_item["pdf_render_time"] = round(pdf_render_time, 4)
            new_item["chunk_pred_time"] = round(chunk_pred_time_total, 4)
            new_item["summary_pred_time"] = round(summary_pred_time, 4)
            new_item["pred_time"] = round(total_pred_time, 4)

            print("\n" + "=" * 100)
            print(f"[{idx}/{len(data)}] Question:")
            print(question)
            print("-" * 100)
            print("Chunk predictions:")
            for cp in chunk_preds:
                print(f"[Chunk {cp['chunk_id']} | pages {cp['page_start']}-{cp['page_end']}]")
                print(cp["pred"])
                print(f"Chunk pred time: {format_seconds(cp['pred_time'])} ({cp['pred_time']:.4f}s)")
                print("-" * 100)
            print("Final prediction:")
            print(final_pred)
            print("-" * 100)
            print(f"PDF render time  : {format_seconds(pdf_render_time)} ({pdf_render_time:.4f}s)")
            print(f"Chunk infer time : {format_seconds(chunk_pred_time_total)} ({chunk_pred_time_total:.4f}s)")
            print(f"Summary infer time: {format_seconds(summary_pred_time)} ({summary_pred_time:.4f}s)")
            print(f"Total infer time : {format_seconds(total_pred_time)} ({total_pred_time:.4f}s)")
            print("=" * 100)

        except Exception as e:
            new_item["pred"] = ""
            new_item["chunk_preds"] = []
            new_item["pdf_render_time"] = None
            new_item["chunk_pred_time"] = None
            new_item["summary_pred_time"] = None
            new_item["pred_time"] = None
            new_item["error"] = str(e)

            print("\n" + "=" * 100)
            print(f"[{idx}/{len(data)}] Question:")
            print(question)
            print("-" * 100)
            print(f"Error: {e}")
            print("=" * 100)

        results.append(new_item)

        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    total_elapsed = time.time() - total_start
    print(f"\nDone. Saved {len(results)} items to {output_json}")
    print(f"Total wall time: {format_seconds(total_elapsed)} ({total_elapsed:.2f}s)")


if __name__ == "__main__":
    main()
