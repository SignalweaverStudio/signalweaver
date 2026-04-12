from typing import List, Tuple

# Lazy imports — only loaded when SW_MATCHER=embedding is active.
# sentence_transformers requires PyTorch and is optional; naive matching is the default.
_model = None
_np = None
_cosine_similarity = None

MODEL_NAME = "all-MiniLM-L6-v2"


def _load_model():
    global _model, _np, _cosine_similarity
    if _model is not None:
        return
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity as _cs
        _np = np
        _cosine_similarity = _cs
        _model = SentenceTransformer(MODEL_NAME)
    except ImportError as e:
        raise ImportError(
            "SW_MATCHER=embedding requires sentence-transformers and scikit-learn. "
            "Install them or switch back to SW_MATCHER=naive (the default)."
        ) from e


def compute_embeddings(texts: List[str]):
    _load_model()
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

    request_vec = embeddings[0].reshape(1, -1)  # type: ignore[union-attr]
    anchor_vecs = embeddings[1:]

    sims = _cosine_similarity(request_vec, anchor_vecs)[0]

    out: List[Tuple[object, float]] = []
    for anchor, score in zip(anchors, sims):
        if float(score) >= threshold:
            out.append((anchor, float(score)))

    out.sort(key=lambda x: x[1], reverse=True)
    return out