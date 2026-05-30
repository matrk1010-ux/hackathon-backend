import os
from typing import Optional
import numpy as np
import google.generativeai as genai

EMBEDDING_MODEL = "models/text-embedding-004"


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
