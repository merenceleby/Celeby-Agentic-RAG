from rank_bm25 import BM25Okapi
from config import settings
import structlog
from typing import List, Tuple

logger = structlog.get_logger()

class BM25SearchService:
    """BM25 keyword-based search service"""
    
    def __init__(self):
        self.corpus = []
        self.tokenized_corpus = []
        self.bm25 = None
        logger.info("bm25_service_init", status="initialized")
    
    def index_documents(self, documents: List[str]):
        """Index documents for BM25 search"""
        self.corpus = documents
        self.tokenized_corpus = [doc.lower().split() for doc in documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        
        logger.info("bm25_index_created",
                   num_documents=len(documents))
    
    def search(self, query: str, top_k: int = None) -> List[Tuple[str, float]]:
        """
        Search documents using BM25
        
        Args:
            query: Search query
            top_k: Number of top documents to return
            
        Returns:
            List of (document, score) tuples
        """
        if not self.bm25:
            logger.warning("bm25_search_no_index")
            return []
        
        if top_k is None:
            top_k = settings.TOP_K_BM25
        
        tokenized_query = query.lower().split()
        scores = self.bm25.get_scores(tokenized_query)
        
        # Get top-k results
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        
        results = [(self.corpus[i], float(scores[i])) for i in top_indices]
        
        logger.info("bm25_search_completed",
                   query=query,
                   num_results=len(results),
                   top_score=results[0][1] if results else 0)
        
        return results
    
    def get_scores(self, query: str) -> List[float]:
        """Get BM25 scores for all documents"""
        if not self.bm25:
            return []
        
        tokenized_query = query.lower().split()
        return self.bm25.get_scores(tokenized_query).tolist()

# Singleton instance
bm25_service = BM25SearchService()