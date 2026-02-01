from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from config import settings
import structlog
import logging

# Setup structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

logger = structlog.get_logger()

app = FastAPI(
    title="Celeby Agentic RAG",
    description="Advanced RAG system with self-correction, hybrid search, and re-ranking",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

@app.on_event("startup")
async def startup_event():
    logger.info("startup", 
                status="starting",
                ollama_host=settings.OLLAMA_HOST,
                model=settings.OLLAMA_MODEL)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("shutdown", status="stopping")

@app.get("/")
def read_root():
    return {
        "status": "running",
        "name": "Celeby Agentic RAG",
        "version": "2.0.0"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)