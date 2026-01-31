import chromadb
from chromadb.config import Settings as ChromaSettings
from pypdf import PdfReader
from services.embedding import embedding_service
from services.bm25_search import bm25_service
from config import settings
from rank_bm25 import BM25Okapi
import structlog
import os
from typing import List, Dict, Tuple

logger = structlog.get_logger()

class VectorStore:
    """Vector database with hybrid search and BM25 support"""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        
        # BM25 index
        self.bm25 = None
        self.bm25_docs = []
        self.bm25_ids = []
        self.bm25_metadatas = []
        
        # Initialize BM25 from existing documents
        self._rebuild_bm25_index()
        
        logger.info("vector_store_init",
                   path=settings.CHROMA_DB_PATH,
                   collection="documents",
                   total_docs=self.collection.count())
    
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
        
        for pdf_file in pdf_files:
            pdf_path = os.path.join(directory, pdf_file)
            try:
                self.index_document(pdf_path)
            except Exception as e:
                logger.error("pdf_load_error", file=pdf_file, error=str(e))
        
        logger.info("pdf_loading_complete", total_chunks=self.collection.count())
    
    def index_document(self, pdf_path: str) -> dict:
        """Index a single PDF document"""
        filename = os.path.basename(pdf_path)
        logger.info("indexing_document", file=filename)
        
        try:
            # Extract text from PDF
            text = self._extract_text_from_pdf(pdf_path)
            
            if not text or len(text.strip()) < 50:
                logger.warning("document_too_short", file=filename)
                raise ValueError("Document content too short or empty")
            
            # Create chunks
            chunks_data = self._create_chunks(text, filename)
            
            if not chunks_data:
                logger.warning("no_chunks_created", file=filename)
                raise ValueError("No chunks created from document")
            
            # Prepare for ChromaDB
            ids = [chunk["id"] for chunk in chunks_data]
            documents = [chunk["text"] for chunk in chunks_data]
            metadatas = [chunk["metadata"] for chunk in chunks_data]
            
            # Embed chunks
            embeddings = embedding_service.embed_batch(documents)
            
            # Add to ChromaDB
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info("document_indexed",
                       file=filename,
                       chunks=len(chunks_data),
                       total_docs=self.collection.count())
            
            return {
                "path": pdf_path,
                "filename": filename,
                "chunks": len(chunks_data),
                "total_chunks": self.collection.count()
            }
            
        except Exception as e:
            logger.error("index_document_error", file=filename, error=str(e))
            raise
    
    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from PDF"""
        try:
            reader = PdfReader(pdf_path)
            text_parts = []
            
            for page_num, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_parts.append(page_text)
                except Exception as e:
                    logger.warning("page_extract_error",
                                 file=pdf_path,
                                 page=page_num,
                                 error=str(e))
                    continue
            
            full_text = "\n\n".join(text_parts)
            logger.info("pdf_text_extracted",
                       file=os.path.basename(pdf_path),
                       pages=len(reader.pages),
                       chars=len(full_text))
            
            return full_text
            
        except Exception as e:
            logger.error("pdf_read_error", file=pdf_path, error=str(e))
            raise
    
    def _create_chunks(self, text: str, filename: str) -> List[Dict]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks_data = []
        
        chunk_size = settings.CHUNK_SIZE
        chunk_overlap = settings.CHUNK_OVERLAP
        
        for i in range(0, len(words), chunk_size - chunk_overlap):
            chunk_words = words[i:i + chunk_size]
            chunk_text = ' '.join(chunk_words)
            
            if not chunk_text.strip():
                continue
            
            # Add citation
            chunk_id = f"{filename}_chunk_{len(chunks_data)}"
            cited_chunk = f"[Source: {filename}]\n\n{chunk_text}"
            
            chunks_data.append({
                "id": chunk_id,
                "text": cited_chunk,
                "metadata": {
                    "source": filename,
                    "chunk_index": len(chunks_data)
                }
            })
        
        logger.info("chunks_created",
                   file=filename,
                   chunks=len(chunks_data),
                   avg_words=len(words) // max(len(chunks_data), 1))
        
        return chunks_data
    
    def _rebuild_bm25_index(self):
        """Rebuild BM25 index from ALL documents in ChromaDB"""
        logger.info("rebuilding_bm25_index")
        
        try:
            # Get ALL documents from ChromaDB
            all_results = self.collection.get()
            
            if not all_results or not all_results.get("documents"):
                logger.warning("no_documents_for_bm25_rebuild")
                self.bm25 = None
                self.bm25_docs = []
                self.bm25_ids = []
                self.bm25_metadatas = []
                return
            
            documents = all_results["documents"]
            
            # Tokenize for BM25
            tokenized_docs = [doc.lower().split() for doc in documents]
            
            # Create new BM25 object
            self.bm25 = BM25Okapi(tokenized_docs)
            self.bm25_docs = documents
            self.bm25_ids = all_results["ids"]
            self.bm25_metadatas = all_results.get("metadatas", [])
            
            logger.info("bm25_index_rebuilt",
                       num_docs=len(documents),
                       total_tokens=sum(len(tokens) for tokens in tokenized_docs))
            
        except Exception as e:
            logger.error("bm25_rebuild_error", error=str(e))
            # Don't crash, just disable BM25
            self.bm25 = None
            self.bm25_docs = []
    
    def semantic_search(self, query_text: str, top_k: int = None) -> dict:
        """Semantic vector search using embeddings"""
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        query_embedding = embedding_service.embed_text(query_text)
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        documents = results['documents'][0] if results['documents'] else []
        metadatas = results['metadatas'][0] if results['metadatas'] else []
        distances = results['distances'][0] if results['distances'] else []
        
        logger.info("semantic_search",
                   query=query_text[:50],
                   results=len(documents))
        
        return {
            "documents": documents,
            "metadatas": metadatas,
            "distances": distances
        }
    
    def bm25_search(self, query_text: str, top_k: int = None) -> List[Tuple[str, float]]:
        """Keyword search using BM25"""
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        if not self.bm25 or not self.bm25_docs:
            logger.warning("bm25_not_available")
            return []
        
        # Tokenize query
        tokenized_query = query_text.lower().split()
        
        # Get BM25 scores
        scores = self.bm25.get_scores(tokenized_query)
        
        # Get top-k results
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:top_k]
        
        results = [(self.bm25_docs[i], float(scores[i])) for i in top_indices if scores[i] > 0]
        
        logger.info("bm25_search",
                   query=query_text[:50],
                   results=len(results))
        
        return results
    
    def hybrid_search(self, query_text: str, top_k: int = None, alpha: float = 0.5) -> dict:
        """
        Hybrid search combining semantic (vector) and keyword (BM25) search
        
        Args:
            query_text: Search query
            top_k: Number of results to return
            alpha: Weight for semantic search (0-1). 1-alpha for BM25
        
        Returns:
            dict with documents, metadatas, and fused scores
        """
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        # Semantic search
        semantic_results = self.semantic_search(query_text, top_k * 2)
        
        # BM25 search
        bm25_results = self.bm25_search(query_text, top_k * 2)
        
        # Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(
            semantic_results,
            bm25_results,
            alpha=alpha,
            top_k=top_k
        )
        
        logger.info("hybrid_search",
                   query=query_text[:50],
                   semantic_count=len(semantic_results['documents']),
                   bm25_count=len(bm25_results),
                   fused_count=len(fused['documents']))
        
        return fused
    
    def _reciprocal_rank_fusion(self, 
                                semantic_results: dict, 
                                bm25_results: List[Tuple[str, float]], 
                                alpha: float = 0.5,
                                top_k: int = None) -> dict:
        """Fuse semantic and BM25 results using Reciprocal Rank Fusion"""
        if top_k is None:
            top_k = settings.TOP_K_RETRIEVAL
        
        k = 60  # RRF constant
        doc_scores = {}
        
        # Score semantic results
        for rank, doc in enumerate(semantic_results['documents']):
            score = alpha / (k + rank + 1)
            if doc not in doc_scores:
                idx = rank
                doc_scores[doc] = {
                    'score': 0,
                    'metadata': semantic_results['metadatas'][idx] if idx < len(semantic_results['metadatas']) else {}
                }
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
        final_top_k = min(top_k, len(sorted_docs))
        
        return {
            "documents": [doc for doc, _ in sorted_docs[:final_top_k]],
            "metadatas": [data['metadata'] for _, data in sorted_docs[:final_top_k]],
            "scores": [data['score'] for _, data in sorted_docs[:final_top_k]]
        }
    
    def get_all_documents(self) -> List[str]:
        """Get all indexed document texts"""
        try:
            results = self.collection.get()
            return results['documents'] if results and results.get('documents') else []
        except Exception as e:
            logger.error("get_all_documents_error", error=str(e))
            return []
    
    def get_stats(self) -> dict:
        """Get vector store statistics"""
        try:
            total_chunks = self.collection.count()
            bm25_docs = len(self.bm25_docs) if self.bm25_docs else 0
            
            return {
                "total_chunks": total_chunks,
                "bm25_indexed": bm25_docs,
                "collection_name": self.collection.name,
                "bm25_available": self.bm25 is not None
            }
        except Exception as e:
            logger.error("get_stats_error", error=str(e))
            return {
                "total_chunks": 0,
                "bm25_indexed": 0,
                "collection_name": "unknown",
                "bm25_available": False
            }

# Singleton instance
vector_store = VectorStore()