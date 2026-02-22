from typing import List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Load once at startup
MODEL_NAME = "all-MiniLM-L6-v2"
_model = SentenceTransformer(MODEL_NAME)


def compute_embeddings(texts: List[str]) -> np.ndarray:
    # normalize_embeddings=True makes cosine similarity stable and fast
    return _model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)


def find_conflicts_embedding(
    request_summary: str,
    anchors: List,
    threshold: float = 0.60,
) -> List[Tuple[object, float]]:
    """
    Returns list of (anchor, similarity_score) above threshold, sorted by score desc.
    `anchors` are TruthAnchor ORM objects (must have .statement).
    """
    if not anchors:
        return []

    anchor_texts = [a.statement for a in anchors]
    texts = [request_summary] + anchor_texts

    embeddings = compute_embeddings(texts)

    request_vec = embeddings[0].reshape(1, -1)
    anchor_vecs = embeddings[1:]

    sims = cosine_similarity(request_vec, anchor_vecs)[0]

    out: List[Tuple[object, float]] = []
    for anchor, score in zip(anchors, sims):
        if float(score) >= threshold:
            out.append((anchor, float(score)))

    out.sort(key=lambda x: x[1], reverse=True)
    return out