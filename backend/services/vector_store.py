import chromadb
from chromadb.config import Settings as ChromaSettings
from config import settings
from services.embedding import embedding_service
from services.bm25_search import bm25_service
from pypdf import PdfReader
import os
import structlog
from typing import List, Dict

logger = structlog.get_logger()

class VectorStore:
    """Vector database with hybrid search support"""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        logger.info("vector_store_init",
                   path=settings.CHROMA_DB_PATH,
                   collection="documents")
    
    def load_pdfs(self, directory: str = "/app/data/documents"):
        """Load and index all PDFs from directory"""
        if not os.path.exists(directory):
            logger.warning("pdf_directory_not_found", path=directory)
            os.makedirs(directory, exist_ok=True)
            return
        
        pdf_files = [f for f in os.listdir(directory) if f.endswith('.pdf')]
        
        if not pdf_files:
            logger.warning("no_pdfs_found", path=directory)
            return
        
        logger.info("loading_pdfs", count=len(pdf_files))
        
        all_documents = []
        for pdf_file in pdf_files:
            docs = self._process_pdf(os.path.join(directory, pdf_file))
            all_documents.extend(docs)
        
        # Index for BM25 as well
        doc_texts = [doc["text"] for doc in all_documents]
        bm25_service.index_documents(doc_texts)
        
        logger.info("pdf_loading_complete", total_chunks=len(all_documents))
    
    def _process_pdf(self, pdf_path: str) -> List[Dict]:
        """Process a single PDF file"""
        logger.info("processing_pdf", file=os.path.basename(pdf_path))
        
        try:
            reader = PdfReader(pdf_path)
        except Exception as e:
            logger.error("pdf_read_error", file=pdf_path, error=str(e))
            return []
        
        chunks = []
        metadatas = []
        ids = []
        documents = []
        
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if not text.strip():
                    continue
                
                page_chunks = self._chunk_text(text)
                
                for i, chunk in enumerate(page_chunks):
                    chunk_id = f"{os.path.basename(pdf_path)}_p{page_num}_c{i}"
                    chunks.append(chunk)
                    metadatas.append({
                        "source": os.path.basename(pdf_path),
                        "page": page_num,
                        "chunk_index": i
                    })
                    ids.append(chunk_id)
                    documents.append({
                        "text": chunk,
                        "metadata": metadatas[-1],
                        "id": chunk_id
                    })
            except Exception as e:
                logger.error("page_extract_error",
                           file=pdf_path,
                           page=page_num,
                           error=str(e))
                continue
        
        if chunks:
            embeddings = embedding_service.embed_batch(chunks)
            self.collection.add(
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            logger.info("pdf_indexed",
                       file=os.path.basename(pdf_path),
                       chunks=len(chunks))
        
        return documents
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks with overlap"""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), settings.CHUNK_SIZE - settings.CHUNK_OVERLAP):
            chunk = ' '.join(words[i:i + settings.CHUNK_SIZE])
            if chunk.strip():
                chunks.append(chunk)
        
        return chunks
    
    def semantic_search(self, query_text: str, top_k: int = None) -> dict:
        """Semantic vector search"""
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        query_embedding = embedding_service.embed_text(query_text)
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        logger.info("semantic_search",
                   query=query_text[:50],
                   results=len(results['documents'][0]))
        
        return {
            "documents": results['documents'][0],
            "metadatas": results['metadatas'][0],
            "distances": results['distances'][0]
        }
    
    def hybrid_search(self, query_text: str, top_k: int = None, alpha: float = 0.5) -> dict:
        """
        Hybrid search combining semantic and keyword search
        
        Args:
            query_text: Search query
            top_k: Number of results
            alpha: Weight for semantic search (1-alpha for BM25)
        """
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        # Semantic search
        semantic_results = self.semantic_search(query_text, top_k * 2)
        
        # BM25 search
        bm25_results = bm25_service.search(query_text, top_k * 2)
        
        # Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(
            semantic_results,
            bm25_results,
            alpha=alpha
        )
        
        logger.info("hybrid_search",
                   query=query_text[:50],
                   semantic_count=len(semantic_results['documents']),
                   bm25_count=len(bm25_results),
                   fused_count=len(fused['documents']))
        
        return fused
    
    def _reciprocal_rank_fusion(self, semantic_results: dict, bm25_results: List, alpha: float = 0.5) -> dict:
        """Fuse semantic and BM25 results using RRF"""
        k = 60  # RRF constant
        doc_scores = {}
        
        # Score semantic results
        for rank, (doc, distance) in enumerate(zip(semantic_results['documents'], 
                                                    semantic_results['distances'])):
            score = alpha / (k + rank + 1)
            if doc not in doc_scores:
                doc_scores[doc] = {'score': 0, 'metadata': semantic_results['metadatas'][rank]}
            doc_scores[doc]['score'] += score
        
        # Score BM25 results
        for rank, (doc, bm25_score) in enumerate(bm25_results):
            score = (1 - alpha) / (k + rank + 1)
            if doc not in doc_scores:
                doc_scores[doc] = {'score': 0, 'metadata': {}}
            doc_scores[doc]['score'] += score
        
        # Sort by fused score
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        
        # Return top-k
        top_k = min(settings.TOP_K_RETRIEVAL, len(sorted_docs))
        
        return {
            "documents": [doc for doc, _ in sorted_docs[:top_k]],
            "metadatas": [data['metadata'] for _, data in sorted_docs[:top_k]],
            "scores": [data['score'] for _, data in sorted_docs[:top_k]]
        }
    
    def get_all_documents(self) -> List[str]:
        """Get all indexed documents"""
        results = self.collection.get()
        return results['documents'] if results else []

# Singleton instance
vector_store = VectorStore()