from sentence_transformers import SentenceTransformer
from config import settings
import structlog

logger = structlog.get_logger()

class EmbeddingService:
    def __init__(self):
        logger.info("embedding_service_init", 
                   model=settings.EMBEDDING_MODEL,
                   status="loading")
        
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)
        
        logger.info("embedding_service_init", 
                   model=settings.EMBEDDING_MODEL,
                   status="ready")
    
    def embed_text(self, text: str) -> list[float]:
        """Embed a single text"""
        return self.model.encode(text).tolist()
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in batch"""
        return self.model.encode(texts, show_progress_bar=False).tolist()
    
    def get_embedding_dimension(self) -> int:
        """Get embedding vector dimension"""
        return self.model.get_sentence_embedding_dimension()

# Singleton instance
embedding_service = EmbeddingService()