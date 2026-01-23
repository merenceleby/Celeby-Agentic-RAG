from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Ollama Config
    OLLAMA_HOST: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "phi3:mini"
    
    # Database Config
    CHROMA_DB_PATH: str = "/app/chroma_db"
    
    # Redis Config
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_TTL: int = 3600  # 1 hour cache
    
    # Model Config
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    
    # RAG Parameters
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    TOP_K_RETRIEVAL: int = 20
    TOP_K_RERANK: int = 5
    TOP_K_BM25: int = 10
    
    # Agent Parameters
    MAX_CORRECTION_ATTEMPTS: int = 2
    NUM_QUERY_VARIATIONS: int = 3
    
    # Evaluation
    TEST_DATASET_SIZE: int = 50
    
    class Config:
        env_file = ".env"

settings = Settings()