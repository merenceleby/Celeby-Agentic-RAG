from sentence_transformers import CrossEncoder
from config import settings
import structlog
from typing import List, Tuple

logger = structlog.get_logger()

class RerankerService:
    """Cross-encoder based re-ranking service"""
    
    def __init__(self):
        logger.info("reranker_service_init",
                   model=settings.RERANKER_MODEL,
                   status="loading")
        
        self.model = CrossEncoder(settings.RERANKER_MODEL)
        
        logger.info("reranker_service_init",
                   model=settings.RERANKER_MODEL,
                   status="ready")
    
    def rerank(self, query: str, documents: List[str], top_k: int = None) -> List[Tuple[str, float]]:
        """
        Re-rank documents using cross-encoder
        
        Args:
            query: Search query
            documents: List of documents to rerank
            top_k: Number of top documents to return
            
        Returns:
            List of (document, score) tuples sorted by relevance
        """
        if not documents:
            return []
        
        if top_k is None:
            top_k = settings.TOP_K_RERANK
        
        # Create query-document pairs
        pairs = [[query, doc] for doc in documents]
        
        # Get scores from cross-encoder
        scores = self.model.predict(pairs)
        
        # Sort by score (descending)
        ranked = sorted(
            zip(documents, scores),
            key=lambda x: x[1],
            reverse=True
        )
        
        logger.info("rerank_completed",
                   num_docs=len(documents),
                   top_k=top_k,
                   top_score=float(ranked[0][1]) if ranked else 0)
        
        return ranked[:top_k]
    
    def get_scores(self, query: str, documents: List[str]) -> List[float]:
        """Get relevance scores without sorting"""
        pairs = [[query, doc] for doc in documents]
        return self.model.predict(pairs).tolist()

# Singleton instance
reranker_service = RerankerService()