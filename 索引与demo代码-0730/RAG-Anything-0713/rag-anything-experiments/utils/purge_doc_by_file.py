import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


dotenv_file = os.getenv("DOTENV_FILE", ".env")
load_dotenv(dotenv_path=dotenv_file, override=True)

storage = Path(os.getenv("RAG_STORAGE", "rag_storage"))
target_file = os.getenv("FILE_PATH") or os.getenv("PURGE_FILE_PATH")

if not target_file:
    raise SystemExit("Set FILE_PATH=your.pdf before running this script")

if not storage.exists():
    raise SystemExit(f"RAG_STORAGE does not exist: {storage}")


def load_json(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def backup(path: Path, backup_dir: Path):
    if path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)


stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = storage / f"purge_backup_{stamp}_{Path(target_file).stem}"

status_path = storage / "kv_store_doc_status.json"
status = load_json(status_path) or {}

doc_ids = {
    doc_id
    for doc_id, item in status.items()
    if isinstance(item, dict) and item.get("file_path") == target_file
}

if not doc_ids:
    print(f"No doc_status entry found for file_path={target_file}")
    raise SystemExit(0)

chunk_ids = set()
for doc_id in doc_ids:
    item = status.get(doc_id) or {}
    chunk_ids.update(item.get("chunks_list") or [])

if not chunk_ids:
    chunks = load_json(storage / "kv_store_text_chunks.json") or {}
    chunk_ids.update(
        chunk_id
        for chunk_id, item in chunks.items()
        if isinstance(item, dict) and item.get("full_doc_id") in doc_ids
    )

files_to_backup = [
    "kv_store_doc_status.json",
    "kv_store_full_docs.json",
    "kv_store_text_chunks.json",
    "kv_store_llm_response_cache.json",
    "kv_store_full_entities.json",
    "kv_store_full_relations.json",
    "kv_store_entity_chunks.json",
    "kv_store_relation_chunks.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
]

for name in files_to_backup:
    backup(storage / name, backup_dir)

removed = {}

for name in ["kv_store_doc_status.json", "kv_store_full_docs.json"]:
    path = storage / name
    data = load_json(path)
    if isinstance(data, dict):
        before = len(data)
        for doc_id in doc_ids:
            data.pop(doc_id, None)
        removed[name] = before - len(data)
        save_json(path, data)

path = storage / "kv_store_text_chunks.json"
data = load_json(path)
if isinstance(data, dict):
    before = len(data)
    for chunk_id in list(data):
        item = data.get(chunk_id) or {}
        if chunk_id in chunk_ids or item.get("full_doc_id") in doc_ids:
            data.pop(chunk_id, None)
    removed[path.name] = before - len(data)
    save_json(path, data)

path = storage / "kv_store_llm_response_cache.json"
data = load_json(path)
if isinstance(data, dict):
    before = len(data)
    for key in list(data):
        item = data.get(key) or {}
        if item.get("chunk_id") in chunk_ids:
            data.pop(key, None)
    removed[path.name] = before - len(data)
    save_json(path, data)

for name in ["kv_store_full_entities.json", "kv_store_full_relations.json"]:
    path = storage / name
    data = load_json(path)
    if isinstance(data, dict):
        before = len(data)
        for key in list(data):
            item = data.get(key) or {}
            source_id = str(item.get("source_id", ""))
            if any(chunk_id in source_id for chunk_id in chunk_ids):
                data.pop(key, None)
        removed[name] = before - len(data)
        save_json(path, data)

for name in ["kv_store_entity_chunks.json", "kv_store_relation_chunks.json"]:
    path = storage / name
    data = load_json(path)
    if isinstance(data, dict):
        before = len(data)
        for key in list(data):
            item = data.get(key) or {}
            source_id = str(item.get("source_id", ""))
            if key in chunk_ids or any(chunk_id in source_id for chunk_id in chunk_ids):
                data.pop(key, None)
        removed[name] = before - len(data)
        save_json(path, data)

for name in ["vdb_chunks.json", "vdb_entities.json", "vdb_relationships.json"]:
    path = storage / name
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        before = len(data["data"])
        new_rows = []
        for row in data["data"]:
            source_id = str(row.get("source_id", ""))
            full_doc_id = row.get("full_doc_id")
            row_file = row.get("file_path")
            row_id = row.get("__id__")
            if (
                row_id in chunk_ids
                or full_doc_id in doc_ids
                or row_file == target_file
                or any(chunk_id in source_id for chunk_id in chunk_ids)
            ):
                continue
            new_rows.append(row)
        data["data"] = new_rows
        data["matrix"] = [row.get("vector") for row in new_rows]
        removed[name] = before - len(new_rows)
        save_json(path, data)

print(f"Purged file_path={target_file}")
print(f"Doc IDs: {sorted(doc_ids)}")
print(f"Chunk IDs: {len(chunk_ids)}")
print(f"Backup: {backup_dir}")
for name, count in sorted(removed.items()):
    print(f"{name}: removed {count}")
