from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from models import QueryRequest, QueryResponse, MetricsResponse
from services.agent import rag_agent
from services.vector_store import vector_store
from services.metrics import metrics_tracker
from services.query_analyzer import query_analyzer
from services.feedback import feedback_service
from evaluation.ragas_eval import ragas_evaluator
import structlog
import json
import os

logger = structlog.get_logger()
router = APIRouter()

class FeedbackRequest(BaseModel):
    query: str
    answer: str
    feedback: int
    sources: list = []
    response_time_ms: float = 0

@router.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Query documents with RAG agent"""
    try:
        logger.info("query_request", query=request.query)
        
        # Analyze query (optional metadata)
        analysis = await query_analyzer.analyze_query(request.query)
        
        # Run agent
        result = await rag_agent.run(request.query)
        
        # If no relevant docs found, override answer
        if not result["sources"] or len(result["sources"]) == 0:
            result["answer"] = "I cannot find this information in the provided documents."
        
        # Track metrics
        metrics_tracker.record_query(
            query=request.query,
            latency_ms=result["response_time_ms"],
            was_corrected=result["was_corrected"],
            retrieval_score=result["retrieval_score"],
            cache_hit=False,
            error=False
        )
        
        # Add query analysis to metadata
        result["metadata"]["query_analysis"] = analysis
        
        return QueryResponse(**result)
        
    except Exception as e:
        logger.error("query_error", query=request.query, error=str(e))
        
        # Track error
        metrics_tracker.record_query(
            query=request.query,
            latency_ms=0,
            was_corrected=False,
            retrieval_score=0,
            cache_hit=False,
            error=True
        )
        
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query-stream")
async def query_stream(request: QueryRequest):
    """Query with streaming response"""
    try:
        logger.info("query_stream_request", query=request.query)
        
        import time
        start_time = time.time()
        
        async def generate():
            nonlocal start_time
            response_time_ms = 0
            sources_count = 0
            
            try:
                async for chunk in rag_agent.run_stream(request.query):
                    yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # Track metadata when done
                    if chunk.get('type') == 'metadata' and chunk.get('done'):
                        response_time_ms = (time.time() - start_time) * 1000
                        sources_count = len(chunk.get('content', {}).get('sources', []))
                        
                        # Record metrics
                        metrics_tracker.record_query(
                            query=request.query,
                            latency_ms=response_time_ms,
                            was_corrected=False,  # Stream doesn't do correction
                            retrieval_score=chunk.get('content', {}).get('retrieval_score', 0),
                            cache_hit=False,
                            error=False
                        )
                        
            except Exception as e:
                logger.error("stream_error", error=str(e))
                
                # Record error
                metrics_tracker.record_query(
                    query=request.query,
                    latency_ms=(time.time() - start_time) * 1000,
                    was_corrected=False,
                    retrieval_score=0,
                    cache_hit=False,
                    error=True
                )
                
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error("query_stream_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and automatically index a PDF document"""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        logger.info("upload_request", filename=file.filename)
        
        # Save file
        file_path = f"/app/data/documents/{file.filename}"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Process and index immediately
        documents = vector_store._process_pdf(file_path)
        
        # Re-index BM25 with all documents
        all_docs = vector_store.get_all_documents()
        from services.bm25_search import bm25_service
        bm25_service.index_documents(all_docs)
        
        logger.info("upload_complete", 
                   filename=file.filename,
                   chunks=len(documents))
        
        return {
            "message": f"Document '{file.filename}' uploaded and indexed successfully",
            "filename": file.filename,
            "chunks": len(documents)
        }
        
    except Exception as e:
        logger.error("upload_error", filename=file.filename, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/initialize")
async def initialize_database():
    """Initialize vector database from documents folder"""
    try:
        logger.info("initialize_request")
        
        vector_store.load_pdfs()
        
        logger.info("initialize_complete")
        
        return {
            "message": "Database initialized successfully",
            "status": "ready"
        }
        
    except Exception as e:
        logger.error("initialize_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """Get system metrics"""
    try:
        metrics = metrics_tracker.get_metrics()
        return MetricsResponse(**metrics)
        
    except Exception as e:
        logger.error("metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/metrics/reset")
async def reset_metrics():
    """Reset metrics tracker"""
    try:
        metrics_tracker.reset()
        logger.info("metrics_reset")
        
        return {"message": "Metrics reset successfully"}
        
    except Exception as e:
        logger.error("metrics_reset_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents")
async def get_documents():
    """Get list of uploaded documents"""
    try:
        docs_dir = "/app/data/documents"
        
        if not os.path.exists(docs_dir):
            return {"documents": []}
        
        files = [f for f in os.listdir(docs_dir) if f.endswith('.pdf')]
        
        documents = []
        for filename in files:
            # Get chunk count from vector store
            results = vector_store.collection.get(
                where={"source": filename}
            )
            chunk_count = len(results['ids']) if results else 0
            
            documents.append({
                "name": filename,
                "chunks": chunk_count
            })
        
        logger.info("documents_listed", count=len(documents))
        
        return {"documents": documents}
        
    except Exception as e:
        logger.error("get_documents_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """Delete a document and remove from vector store"""
    try:
        from urllib.parse import unquote
        
        filename = unquote(filename)
        file_path = f"/app/data/documents/{filename}"
        
        logger.info("delete_document_start", filename=filename)
        
        # Delete from vector store (by source metadata)
        try:
            # Get all IDs for this document
            results = vector_store.collection.get(
                where={"source": filename}
            )
            
            if results and results['ids']:
                # Delete by IDs
                vector_store.collection.delete(ids=results['ids'])
                logger.info("document_deleted_from_vectorstore", 
                           filename=filename,
                           chunks_deleted=len(results['ids']))
            else:
                logger.warning("no_chunks_found_in_vectorstore", filename=filename)
                
        except Exception as e:
            logger.error("vectorstore_delete_error", filename=filename, error=str(e))
            raise HTTPException(status_code=500, detail=f"Failed to delete from vector store: {str(e)}")
        
        # Clear cache
        from services.cache import cache_service
        cache_service.clear_pattern("retrieval:*")
        logger.info("cache_cleared_after_delete")
        
        # Re-index BM25 with remaining documents
        from services.bm25_search import bm25_service
        all_docs = vector_store.get_all_documents()
        
        if all_docs:
            bm25_service.index_documents(all_docs)
            logger.info("bm25_reindexed", doc_count=len(all_docs))
        else:
            bm25_service.corpus = []
            bm25_service.tokenized_corpus = []
            bm25_service.bm25 = None
            logger.info("bm25_cleared_no_docs")
        
        # Delete file from disk
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("document_file_deleted", filename=filename)
        else:
            logger.warning("file_not_found_on_disk", filename=filename)
        
        return {
            "message": f"Document '{filename}' deleted successfully",
            "filename": filename,
            "chunks_removed": len(results['ids']) if results and results['ids'] else 0
        }
        
    except Exception as e:
        logger.error("delete_document_error", filename=filename, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Submit user feedback on an answer"""
    try:
        feedback_id = feedback_service.add_feedback(
            query=request.query,
            answer=request.answer,
            feedback=request.feedback,
            sources=request.sources,
            response_time_ms=request.response_time_ms
        )
        
        logger.info("feedback_submitted",
                   feedback_id=feedback_id,
                   feedback="like" if request.feedback == 1 else "dislike")
        
        return {
            "message": "Feedback submitted successfully",
            "feedback_id": feedback_id
        }
        
    except Exception as e:
        logger.error("feedback_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/feedback/stats")
async def get_feedback_stats():
    """Get feedback statistics"""
    try:
        stats = feedback_service.get_feedback_stats()
        return stats
    except Exception as e:
        logger.error("feedback_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/feedback/reset")
async def reset_feedback():
    """Reset all feedback data"""
    try:
        import os
        feedback_db_path = "/app/feedback.db"
        
        if os.path.exists(feedback_db_path):
            os.remove(feedback_db_path)
            logger.info("feedback_db_deleted")
        
        # Reinitialize
        from services.feedback import FeedbackService
        global feedback_service
        feedback_service = FeedbackService()
        
        return {"message": "Feedback reset successfully"}
    except Exception as e:
        logger.error("feedback_reset_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluation/generate-dataset")
async def generate_test_dataset(n_questions: int = 20):
    """Generate synthetic test dataset from indexed documents"""
    try:
        logger.info("generate_dataset_request", n_questions=n_questions)
        
        dataset = await ragas_evaluator.generate_test_dataset(n_questions)
        
        logger.info("generate_dataset_complete", num_cases=len(dataset))
        
        return {
            "message": f"Generated {len(dataset)} test cases",
            "dataset": dataset,
            "description": "These are question-answer pairs automatically generated from your documents for testing the RAG system quality."
        }
        
    except Exception as e:
        logger.error("generate_dataset_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluation/run")
async def run_evaluation(test_cases: list = None):
    """Run RAGAS evaluation to measure RAG system quality"""
    try:
        logger.info("run_evaluation_request")
        
        # If no test cases provided, generate them
        if not test_cases:
            test_cases = await ragas_evaluator.generate_test_dataset(20)
        
        # Run evaluation
        results = await ragas_evaluator.evaluate_system(test_cases, rag_agent)
        
        logger.info("run_evaluation_complete")
        
        # Add explanation
        results["explanation"] = {
            "faithfulness": "Measures if the answer is factually accurate based on the retrieved context (0-1, higher is better)",
            "relevancy": "Measures if the answer is relevant to the question asked (0-1, higher is better)",
            "recall": "Measures if the system retrieved the right documents to answer the question (0-1, higher is better)"
        }
        
        return results
        
    except Exception as e:
        logger.error("run_evaluation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "rag-agent"
    }