"""Multilingual Semantic Embedding Service for ErasmusMatch.

Uses sentence-transformers with 'paraphrase-multilingual-MiniLM-L12-v2'
to produce 384-dimensional dense semantic vectors across 50+ languages.
"""

from typing import List, Union
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from backend.app.core.config import settings


class EmbeddingService:
    """Manages loading and inference of the multilingual sentence transformer model."""

    def __init__(self, model_name: str = settings.EMBEDDING_MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self.dimension = settings.EMBEDDING_DIMENSION
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loader for the SentenceTransformer model."""
        if self._model is None:
            print(f"🧠 Loading embedding model '{self.model_name}' on device '{self.device}'...")
            self._model = SentenceTransformer(self.model_name, device=self.device)
            print("✅ Model loaded successfully!")
        return self._model

    def embed_text(self, text: str) -> List[float]:
        """Encodes a single text into a normalized 384-dim vector."""
        cleaned_text = text.strip()
        if not cleaned_text:
            return [0.0] * self.dimension
        embedding = self.model.encode(
            cleaned_text,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
        return embedding.tolist()

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Encodes a batch of texts into normalized 384-dim vectors."""
        cleaned_texts = [t.strip() if t.strip() else "Empty course syllabus" for t in texts]
        embeddings = self.model.encode(
            cleaned_texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True
        )
        return embeddings.tolist()

    @staticmethod
    def cosine_similarity(vec1: Union[List[float], np.ndarray], vec2: Union[List[float], np.ndarray]) -> float:
        """Computes cosine similarity between two normalized vectors."""
        v1 = np.asarray(vec1)
        v2 = np.asarray(vec2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))


# Global singleton instance
embedding_service = EmbeddingService()

