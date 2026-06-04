import os
from typing import Optional
import numpy as np
import google.generativeai as genai

# text-embedding-004 は廃止され embedContent では 404 になるため、
# 現行の gemini-embedding-001 を使用する（既定3072次元）。
EMBEDDING_MODEL = "models/gemini-embedding-001"


def get_embedding(text: str) -> Optional[list]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        result = genai.embed_content(model=EMBEDDING_MODEL, content=text)
        return result["embedding"]
    except Exception:
        return None


def cosine_similarity(a: list, b: list) -> float:
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
