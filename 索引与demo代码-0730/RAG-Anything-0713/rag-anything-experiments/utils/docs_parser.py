#!/usr/bin/env python3
"""
Flexible PDF Parser: MinerU > PaddleOCR > Docling
Supports single file or recursive folder search. Usage: python parser.py folder/ --tool mineru
"""

import argparse
import sys
import os
from pathlib import Path
import subprocess
import json
from typing import Optional, List
import glob
import time
from functools import wraps
from dotenv import load_dotenv

dotenv_file = os.getenv('DOTENV_FILE', '.env')
load_dotenv(dotenv_path=dotenv_file, override=True)

def timer(func):
    """Simple timer decorator for profiling [your preference]."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"{func.__name__} took {time.time() - start:.2f}s")
        return result
    return wrapper

def find_pdfs(input_path: Path) -> List[Path]:
    """Recursive PDF search."""
    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        return [input_path]
    elif input_path.is_dir():
        pdfs = list(input_path.rglob("*.pdf"))
        print(f"Found {len(pdfs)} PDFs in {input_path}")
        return pdfs
    else:
        raise ValueError(f"Invalid path: {input_path}")

def parse_with_mineru(pdf_path: Path, output_dir: Path, vlm: False) -> Optional[str]:
    """MinerU: Best for complex docs/tables/formulas."""
    try:
        pdf_str = str(pdf_path)
        out_subdir = output_dir / pdf_path.parent.relative_to(pdf_path.anchor).as_posix().replace('/', '_')
        out_subdir.mkdir(parents=True, exist_ok=True)
        cmd = []
        md_file = ""
        if vlm:
            print("MinerU backend: vlm")
            cmd = [
                "uv", "run", "mineru", "-p", pdf_str,
                "--output", str(out_subdir),
                "--method", "auto",
                "--backend", "vlm-auto-engine",
            ]
            md_file = out_subdir /f"{pdf_path.stem}" / "vlm" / f"{pdf_path.stem}.md"
        else:
            print("MinerU backend: pipeline")
            cmd = [
            "uv", "run", "mineru",
            "-p", str(pdf_path),
            "-o", str(out_subdir),
            "-b", "pipeline",
            ]
            md_file = out_subdir /f"{pdf_path.stem}" / "auto" / f"{pdf_path.stem}.md"
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        print(md_file)
        if md_file.exists():
            return md_file.read_text(encoding='utf-8')
        print(f"MinerU no MD: {result.stdout}")
        return None
    except Exception as e:
        print(f"MinerU failed on {pdf_path}: {e}")
        return None

def parse_with_paddleocr(pdf_path: Path) -> Optional[str]:
    """PaddleOCR: Fast OCR."""
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)
        result = ocr.ocr(str(pdf_path), cls=True)
        text = '\n\n'.join([line[1][0] for page in result for line in page if line])
        return f"# {pdf_path.name}\n\n{text}"
    except Exception as e:
        print(f"PaddleOCR failed on {pdf_path}: {e}")
        return None

def parse_with_docling(pdf_path: Path) -> Optional[str]:
    """Docling: Layout Markdown."""
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        converter = DocumentConverter(format_options={InputFormat.PDF: PdfPipelineOptions()})
        doc = converter.convert(str(pdf_path))
        return doc.to_markdown()
    except Exception as e:
        print(f"Docling failed on {pdf_path}: {e}")
        return None

@timer
def process_pdf(pdf_path: Path, tool: str, output_dir: Path, vlm: False) -> bool:
    """Process single PDF."""
    if tool == "mineru":
        content = parse_with_mineru(pdf_path, output_dir, vlm)
    elif tool == "paddleocr":
        content = parse_with_paddleocr(pdf_path)
    elif tool == "docling":
        content = parse_with_docling(pdf_path)
    else:
        print(f"Unknown tool: {tool}")
        return False

    if content:
        # For non-MinerU, save to output dir mirroring structure
        out_subdir = output_dir / pdf_path.parent.relative_to(pdf_path.anchor).as_posix().replace('/', '_')
        out_subdir.mkdir(parents=True, exist_ok=True)
        out_file = out_subdir / f"{pdf_path.stem}_parsed.md"
        out_file.write_text(content, encoding='utf-8')
        print(f"✓ {pdf_path.name} → {out_file}")
        return True
    return False

def main():
    parser = argparse.ArgumentParser(description="Batch PDF Parser (recursive folders)")
    parser.add_argument("--input", default=os.getenv("DOCS_PATH", ""), help="PDF file or folder")
    parser.add_argument("--tool", choices=["mineru", "paddleocr", "docling"], default=os.getenv("PARSER_NAME", "mineru"))
    parser.add_argument("--output", "-o", default=os.getenv("PARSER_OUTPUT_DIR", os.getenv("PARSER_NAME", "mineru")+"_output"), help="Output dir")
    parser.add_argument("--dry-run", action="store_true", help="List PDFs only")
    parser.add_argument("--vlm", action="store_true", help="option for minerU to use vlm backend")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)

    pdfs = find_pdfs(input_path)
    vlm_enabled = os.getenv('MINERU_VLM', args.vlm).lower() == 'true'
    if not pdfs:
        print("No PDFs found.")
        sys.exit(1)

    if args.dry_run:
        for p in pdfs:
            print(p)
        return

    success = 0
    for pdf in pdfs:
        if process_pdf(pdf, args.tool, output_dir, vlm_enabled):
            success += 1
        else:
            print(f"✗ Failed: {pdf}")

    print(f"\nProcessed {success}/{len(pdfs)} PDFs in {output_dir}")

if __name__ == "__main__":
    main()
