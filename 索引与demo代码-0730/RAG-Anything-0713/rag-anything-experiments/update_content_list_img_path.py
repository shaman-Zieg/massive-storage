#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path

"""
python update_content_list_img_path.py mineru_parsed
"""

def convert_img_path(
    old_path: str,
    marker: str = "output_unidocbench_sampled10",
    new_prefix: str = "mineru-parsed",
) -> str:
    """
    Convert old img_path to target format.

    Example:
      /home/RAG-Anything/output_unidocbench_sampled10/commerce_manufacturing_0501317/auto/images/a.jpg

    To:
      mineru-parsed/commerce_manufacturing_0501317/auto/images/a.jpg

    Notes:
      - Always use '/' as path separator, even on Windows.
      - If marker is not found, keep original path unchanged.
    """

    if not isinstance(old_path, str):
        return old_path

    # Windows 下可能出现反斜杠，统一转成正斜杠
    normalized_path = old_path.replace("\\", "/")

    parts = normalized_path.split("/")

    if marker not in parts:
        return old_path

    marker_idx = parts.index(marker)

    # marker 后面的部分：
    # commerce_manufacturing_0501317/auto/images/a.jpg
    relative_parts = parts[marker_idx + 1:]

    if not relative_parts:
        return old_path

    return new_prefix + "/" + "/".join(relative_parts)


def update_img_path_recursive(obj) -> bool:
    """
    Recursively update img_path in dict/list JSON object.

    Return:
      True  - content changed
      False - content unchanged
    """

    changed = False

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "img_path" and isinstance(value, str):
                new_value = convert_img_path(value)

                if new_value != value:
                    obj[key] = new_value
                    changed = True
            else:
                if update_img_path_recursive(value):
                    changed = True

    elif isinstance(obj, list):
        for item in obj:
            if update_img_path_recursive(item):
                changed = True

    return changed


def process_json_file(json_file: Path, dry_run: bool = False) -> bool:
    """
    Process one *content_list.json file.

    Return:
      True  - file updated or would be updated in dry-run mode
      False - no change
    """

    try:
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {json_file}")
        print(f"        {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to read: {json_file}")
        print(f"        {e}")
        return False

    changed = update_img_path_recursive(data)

    if changed:
        if dry_run:
            print(f"[DRY-RUN] Would update: {json_file}")
        else:
            try:
                with json_file.open("w", encoding="utf-8", newline="\n") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.write("\n")

                print(f"[UPDATED] {json_file}")
            except Exception as e:
                print(f"[ERROR] Failed to write: {json_file}")
                print(f"        {e}")
                return False
    else:
        print(f"[SKIP]    {json_file}")

    return changed


def find_content_list_files(root_dir: Path):
    """
    Find all *content_list.json files recursively.
    """

    return sorted(root_dir.rglob("*content_list.json"))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Recursively find all *content_list.json files and update "
            "their img_path fields to mineru-parsed/... format."
        )
    )

    parser.add_argument(
        "root_dir",
        type=str,
        help="Top-level folder path, e.g. /home/RAG-Anything/output_unidocbench_sampled10",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show files that would be updated, without modifying them.",
    )

    parser.add_argument(
        "--marker",
        type=str,
        default="output_unidocbench_sampled10",
        help="Path marker used to cut old absolute path. Default: output_unidocbench_sampled10",
    )

    parser.add_argument(
        "--new-prefix",
        type=str,
        default="mineru-parsed",
        help="New path prefix. Default: mineru-parsed",
    )

    args = parser.parse_args()

    root_dir = Path(args.root_dir).resolve()

    if not root_dir.exists():
        raise FileNotFoundError(f"Root directory does not exist: {root_dir}")

    if not root_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root_dir}")

    # 让 convert_img_path 使用命令行传入的 marker 和 new_prefix
    def convert_with_args(old_path: str) -> str:
        return convert_img_path(
            old_path=old_path,
            marker=args.marker,
            new_prefix=args.new_prefix,
        )

    def update_with_args(obj) -> bool:
        changed = False

        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "img_path" and isinstance(value, str):
                    new_value = convert_with_args(value)

                    if new_value != value:
                        obj[key] = new_value
                        changed = True
                else:
                    if update_with_args(value):
                        changed = True

        elif isinstance(obj, list):
            for item in obj:
                if update_with_args(item):
                    changed = True

        return changed

    def process_with_args(json_file: Path) -> bool:
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {json_file}")
            print(f"        {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Failed to read: {json_file}")
            print(f"        {e}")
            return False

        changed = update_with_args(data)

        if changed:
            if args.dry_run:
                print(f"[DRY-RUN] Would update: {json_file}")
            else:
                try:
                    with json_file.open("w", encoding="utf-8", newline="\n") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.write("\n")

                    print(f"[UPDATED] {json_file}")
                except Exception as e:
                    print(f"[ERROR] Failed to write: {json_file}")
                    print(f"        {e}")
                    return False
        else:
            print(f"[SKIP]    {json_file}")

        return changed

    json_files = find_content_list_files(root_dir)

    print(f"Root dir: {root_dir}")
    print(f"Found {len(json_files)} *content_list.json files")

    updated_count = 0

    for json_file in json_files:
        if process_with_args(json_file):
            updated_count += 1

    print()
    print(f"Done. Updated {updated_count}/{len(json_files)} files.")


if __name__ == "__main__":
    main()