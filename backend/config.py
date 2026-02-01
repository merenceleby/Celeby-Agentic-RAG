from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    # Ollama Config
    OLLAMA_HOST: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "phi3:mini"
    
    # Database Config
    CHROMA_DB_PATH: str = "/app/chroma_db"
    METRICS_DB_PATH: str = "/app/metrics.db"
    CHAT_HISTORY_DB_PATH: str = "/app/chat_history.db"
    
    # Redis Config
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_TTL: int = 3600  # 1 hour cache
    
    # Model Config
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    
    # RAG Parameters - OPTIMIZED FOR QUALITY
    CHUNK_SIZE: int = 1024  
    CHUNK_OVERLAP: int = 256  # Increased for better context
    TOP_K_RETRIEVAL: int = 20  # Reduced to focus on best matches
    TOP_K_RERANK: int = 7
    TOP_K_BM25: int = 10
    RERANK_THRESHOLD: float = -5.0  # Stricter threshold -2.0 to -5.00
    
    # Agent Parameters - MODE BASED
    FAST_MODE: bool = os.getenv("FAST_MODE", "false").lower() == "true"
    MAX_CORRECTION_ATTEMPTS: int = 0 if os.getenv("FAST_MODE", "false").lower() == "true" else 2
    NUM_QUERY_VARIATIONS: int = 1 if os.getenv("FAST_MODE", "false").lower() == "true" else 3
    
    # Search Mode: local, web, auto
    SEARCH_MODE: str = os.getenv("SEARCH_MODE", "local")
    
    # Evaluation
    TEST_DATASET_SIZE: int = 50
    
    class Config:
        env_file = ".env"

settings = Settings()
