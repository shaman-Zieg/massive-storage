from pathlib import Path
import json
import os
from dotenv import load_dotenv

dotenv_file = os.getenv('DOTENV_FILE', '.env')
load_dotenv(dotenv_path=dotenv_file, override=True)
print("HELLO")
OUTPUT_DIR = os.getenv("PARSER_OUTPUT_DIR", os.getenv("PARSER_NAME", "mineru")+"_output")
root = Path(f"{OUTPUT_DIR}")
print(root)
for json_path in root.rglob("*_content_list.json"):
    print(f"Reading json: {json_path}")
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

        changed = False
    base_dir = json_path.parent  # this is the auto/ folder

    for item in data:
        if isinstance(item, dict) and isinstance(item.get("img_path"), str):
            p = item["img_path"].replace("\\", "/")
            if p.startswith("images/"):
                full_path = str(base_dir / p)
                if item["img_path"] != full_path:
                    item["img_path"] = full_path
                    changed = True

    if changed:
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Updated: {json_path}")
    else:
        print(f"No change: {json_path}")
