import os
import uuid
import asyncio
from typing import List, Dict, Optional
from dotenv import load_dotenv, dotenv_values
from openai import AsyncOpenAI
import logging
import logging.config
from pathlib import Path
import json
from collections import Counter
# Load environment variables
import time

dotenv_file = os.getenv('DOTENV_FILE', '.env')
load_dotenv(dotenv_path=dotenv_file, override=True)
config = dotenv_values(dotenv_file)
print(config)

LLM_MODEL = os.getenv("LLM_MODEL", "")
VLLM_MODEL  = os.getenv("VLLM_MODEL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
VLLM_BINDING_HOST = os.getenv("VLLM_BINDING_HOST", "")
LLM_BINDING_HOST = os.getenv("LLM_BINDING_HOST", "")
EMBEDDING_BINDING_HOST = os.getenv("EMBEDDING_BINDING_HOST", "")

MODELS = [
    [LLM_MODEL, LLM_BINDING_HOST, "local"],
    [VLLM_MODEL, VLLM_BINDING_HOST, "local"],
    [EMBEDDING_MODEL, EMBEDDING_BINDING_HOST, "local"],
]

async def test_connection() -> bool:
    try:
        for mod in MODELS:
            base_url = mod[1]
            model_name = mod[0]
            print(f"🔌 Testing vLLM connection at: {base_url}")
            client = AsyncOpenAI(base_url=base_url, api_key=mod[2])
            models = await client.models.list()
            print(f"✅ Connected successfully! Found {len(models.data)} models")

            # Show available models
            print("📊 Available models:")
            for i, model in enumerate(models.data[:5]):
                marker = "🎯" if model.id == model_name else "  "
                print(f"{marker} {i+1}. {model.id}")

            if len(models.data) > 5:
                print(f"  ... and {len(models.data) - 5} more models")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {str(e)}")
        print("\n💡 Troubleshooting tips:")
        print("1. Ensure vLLM server is running:")
        print("   vllm serve Qwen/Qwen2.5-72B-Instruct")
        print(f"2. Verify server address: {base_url}")
        print("3. Check that the model has finished loading")
        print("4. If using authentication, verify your API key")
        return False
    finally:
        try:
            await client.close()
        except Exception:
            pass

asyncio.run(test_connection())
