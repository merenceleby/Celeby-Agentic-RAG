# 🤖 Self-Correcting RAG Agent

Advanced Retrieval-Augmented Generation system with self-correction, hybrid search, cross-encoder re-ranking, and comprehensive evaluation.

## 🌟 Features

### Core Capabilities
- ✅ **Self-Correction Mechanism** - Validates and corrects answers automatically using LangGraph
- 🔄 **Query Rewriting** - Generates multiple query variations for better retrieval
- 🔍 **Hybrid Search** - Combines semantic (vector) and keyword (BM25) search with RRF
- 🎯 **Cross-Encoder Re-ranking** - Uses state-of-the-art re-ranking for top results
- ⚡ **Streaming Responses** - Real-time answer generation with ChatGPT-style streaming
- 📊 **RAGAS Evaluation** - Automated quality assessment (faithfulness, relevancy, recall)
- 💾 **Redis Caching** - Fast response times with intelligent caching
- 📈 **Comprehensive Metrics** - Real-time performance tracking and monitoring

### Technical Stack
- **LLM**: Phi-3 Mini (via Ollama)
- **Framework**: LangGraph for agent orchestration
- **Vector DB**: ChromaDB with persistent storage
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **Re-ranker**: Cross-encoder (ms-marco-MiniLM-L-6-v2)
- **Keyword Search**: BM25 with rank fusion
- **Cache**: Redis
- **Backend**: FastAPI with async support
- **Frontend**: React + Vite

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- 8GB+ RAM recommended
- ~10GB disk space for models

### Installation

1. **Clone and navigate**
```bash
git clone <your-repo>
cd rag-agent
```

2. **Start all services**
```bash
docker-compose up -d
```

3. **Pull the Phi-3 model**
```bash
docker exec -it ollama ollama pull phi3:mini
```

4. **Add your documents**
```bash
# Place PDF files in backend/data/documents/
cp your-documents/*.pdf backend/data/documents/
```

5. **Initialize the database**
- Open http://localhost:5173
- Click "🔄 Initialize DB" button

6. **Start querying!**

## 📁 Project Structure

```
rag-agent/
├── backend/
│   ├── api/                    # FastAPI routes
│   ├── services/               # Core services
│   │   ├── agent.py           # LangGraph RAG agent
│   │   ├── llm.py             # Ollama LLM service
│   │   ├── vector_store.py    # ChromaDB + BM25
│   │   ├── reranker.py        # Cross-encoder re-ranking
│   │   ├── cache.py           # Redis caching
│   │   ├── metrics.py         # Metrics tracking
│   │   └── query_analyzer.py  # Query understanding
│   ├── evaluation/            # RAGAS evaluation
│   ├── models/                # Pydantic models
│   └── config.py              # Configuration
├── frontend/
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── App.jsx
│   │   └── main.jsx
│   └── Dockerfile
└── docker-compose.yml
```

## 🔧 Configuration

Edit `backend/config.py` to customize:

```python
# Model Configuration
OLLAMA_MODEL = "phi3:mini"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# RAG Parameters
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
TOP_K_RETRIEVAL = 20
TOP_K_RERANK = 5
TOP_K_BM25 = 10

# Agent Parameters
MAX_CORRECTION_ATTEMPTS = 2
NUM_QUERY_VARIATIONS = 3
```

## 📊 API Endpoints

### Query
```bash
POST /api/query
{
  "query": "What is the main topic?"
}
```

### Streaming Query
```bash
POST /api/query-stream
{
  "query": "Explain in detail..."
}
```

### Upload Document
```bash
POST /api/upload
Content-Type: multipart/form-data
file: document.pdf
```

### Metrics
```bash
GET /api/metrics
```

### Evaluation
```bash
# Generate test dataset
POST /api/evaluation/generate-dataset?n_questions=20

# Run evaluation
POST /api/evaluation/run
```

## 🧪 Evaluation

The system includes automated RAGAS-style evaluation:

```python
# Generate synthetic test dataset
POST /api/evaluation/generate-dataset?n_questions=50

# Run evaluation
POST /api/evaluation/run
```

Metrics calculated:
- **Faithfulness**: Answer accuracy vs context
- **Answer Relevancy**: Answer relevance to question
- **Context Recall**: Retrieval quality

## 📈 Monitoring

Access real-time metrics at http://localhost:5173:
- Total queries processed
- Average latency (P95, P99)
- Self-correction rate
- Cache hit rate
- System uptime

## 🎯 FAANG Interview Highlights

This project demonstrates:

1. **System Design**
   - Scalable microservices architecture
   - Caching strategy for performance
   - Async/await for concurrency

2. **Advanced RAG Techniques**
   - Hybrid search (semantic + keyword)
   - Cross-encoder re-ranking
   - Query understanding and rewriting
   - Self-correction mechanism

3. **Production-Ready Features**
   - Structured logging
   - Metrics tracking
   - Error handling
   - Streaming responses

4. **Evaluation & Testing**
   - Automated test dataset generation
   - Quantitative metrics (RAGAS)
   - A/B testing capability

## 🔍 How It Works

### RAG Pipeline

1. **Query Analysis** - Understand intent and complexity
2. **Query Rewriting** - Generate 3 variations
3. **Hybrid Retrieval** - Semantic (vector) + Keyword (BM25)
4. **Re-ranking** - Cross-encoder scores top-k
5. **Generation** - LLM generates answer
6. **Validation** - Check answer quality
7. **Self-Correction** - Retry if needed (max 2 attempts)

### Self-Correction Flow

```
User Query → Rewrite → Retrieve → Rerank → Generate → Validate
                ↑                                           ↓
                └─────────── Correction Loop ←──────────────┘
                              (if incorrect)
```

## 🐛 Troubleshooting

### Ollama not responding
```bash
docker restart ollama
docker exec -it ollama ollama list
```

### ChromaDB errors
```bash
docker-compose down -v
docker-compose up -d
# Re-initialize database
```

### Out of memory
```bash
# Reduce batch sizes in config.py
TOP_K_RETRIEVAL = 10
CHUNK_SIZE = 256
```

## 📚 References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [ChromaDB Docs](https://docs.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [RAGAS Framework](https://docs.ragas.io/)

## 🤝 Contributing

This is a portfolio project. Feel free to fork and modify!

## 📄 License

MIT License

---

**Built for FAANG interviews** 🚀 | Showcasing advanced RAG, system design, and production-ready code