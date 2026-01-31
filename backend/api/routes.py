from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from models import QueryRequest, QueryResponse, MetricsResponse
from config import settings
from services.agent import rag_agent
from services.vector_store import vector_store
from services.metrics import metrics_tracker
from services.query_analyzer import query_analyzer
from services.feedback import feedback_service
from services.chat_history import chat_history_service
from services.llm import llm_service
from services.cache import cache_service
from evaluation.ragas_eval import ragas_evaluator
import structlog
import json
import os
import time
import asyncio

logger = structlog.get_logger()
router = APIRouter()

VALID_CHAT_MODES = {"fast", "quality", "direct"}
CHAT_HISTORY_LIMIT = 8

def _normalize_mode(mode: str | None) -> str:
    if not mode:
        return "quality"
    mode_lower = mode.lower()
    return mode_lower if mode_lower in VALID_CHAT_MODES else "quality"

def _conversation_title_from_query(query: str) -> str:
    cleaned = (query or "").strip()
    if not cleaned:
        return "New Chat"
    return cleaned[:80]

def _ensure_conversation(conversation_id: str | None, query: str) -> str:
    """Create conversation only if none exists"""
    if conversation_id:
        return conversation_id
    title = _conversation_title_from_query(query)
    new_id = chat_history_service.create_conversation(title=title)
    logger.info("conversation_auto_created", id=new_id, title=title)
    return new_id

def _maybe_update_conversation_title(conversation_id: str, query: str):
    conversation = chat_history_service.get_conversation(conversation_id)
    if not conversation:
        return
    if conversation.get("message_count", 0) == 0 or conversation.get("title") in ("New Chat", ""):
        chat_history_service.update_conversation_title(
            conversation_id,
            _conversation_title_from_query(query)
        )

def _format_history_prompt(history: list[dict] | None) -> str:
    if not history:
        return ""
    trimmed = history[-10:]
    lines = []
    for item in trimmed:
        role = "User" if item.get("role") == "user" else "Assistant"
        content = (item.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)

def _get_recent_history(conversation_id: str, include_current: bool = False) -> list[dict]:
    if not conversation_id:
        return []
    history = chat_history_service.get_conversation_history(
        conversation_id,
        limit=CHAT_HISTORY_LIMIT + 2
    )
    if not include_current and history and history[-1].get("role") == "user":
        history = history[:-1]
    return history[-CHAT_HISTORY_LIMIT:]

async def _run_direct_mode(query: str, chat_history: list[dict] | None = None) -> dict:
    """Direct LLM call without retrieval."""
    start_time = time.time()
    system_prompt = (
        "You are a helpful assistant. Answer the user's question directly "
        "without referencing uploaded documents."
    )
    history_prompt = _format_history_prompt(chat_history)
    prompt_parts = []
    if history_prompt:
        prompt_parts.append("Conversation history:\n" + history_prompt)
    prompt_parts.append(f"User Question: {query}")
    prompt_parts.append("Answer directly. Reference the conversation when it helps.")
    prompt = "\n\n".join(prompt_parts)
    answer = await llm_service.generate(prompt, system_prompt=system_prompt)
    response_time_ms = (time.time() - start_time) * 1000
    return {
        "answer": answer.strip(),
        "sources": [],
        "correction_attempts": 0,
        "was_corrected": False,
        "retrieval_score": 0.0,
        "response_time_ms": response_time_ms,
        "metadata": {"mode": "direct"}
    }

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
        mode = _normalize_mode(request.mode)
        conversation_id = _ensure_conversation(request.conversation_id, request.query)
        logger.info("query_request", query=request.query, mode=mode, conversation_id=conversation_id)
        
        _maybe_update_conversation_title(conversation_id, request.query)
        chat_history_service.add_message(
            conversation_id,
            "user",
            request.query,
            metadata={"mode": mode}
        )
        conversation_history = _get_recent_history(conversation_id)
        
        # Analyze query (optional metadata)
        analysis = await query_analyzer.analyze_query(request.query)
        
        # Run agent based on mode
        if mode == "direct":
            result = await _run_direct_mode(request.query, conversation_history)
        elif mode == "fast":
            result = await rag_agent.run_fast(
                request.query,
                chat_history=conversation_history,
                num_query_variations=1
            )
        else:
            result = await rag_agent.run(
                request.query,
                chat_history=conversation_history,
                max_corrections=settings.MAX_CORRECTION_ATTEMPTS,
                num_query_variations=settings.NUM_QUERY_VARIATIONS
            )
        
        # If no relevant docs found, override answer
        if mode != "direct" and (not result["sources"] or len(result["sources"]) == 0):
            result["answer"] = "I cannot find this information in the provided documents."
        
        # Track metrics
        metrics_tracker.record_query(
            query=request.query,
            latency_ms=result["response_time_ms"],
            was_corrected=result["was_corrected"],
            retrieval_score=result["retrieval_score"],
            cache_hit=result.get("cache_hit", False),
            error=False,
            mode=mode
        )
        
        # Add query analysis to metadata
        result["metadata"]["query_analysis"] = analysis
        result["metadata"]["mode"] = mode
        result["conversation_id"] = conversation_id
        
        # Persist assistant answer
        chat_history_service.add_message(
            conversation_id,
            "assistant",
            result["answer"],
            metadata={
                "mode": mode,
                "sources": result["sources"],
                "retrieval_score": result["retrieval_score"],
                "response_time_ms": result["response_time_ms"],
                "was_corrected": result["was_corrected"],
                "correction_attempts": result["correction_attempts"]
            }
        )
        
        return QueryResponse(**result)
        
    except Exception as e:
        mode = _normalize_mode(request.mode)
        logger.error("query_error", query=request.query, error=str(e), mode=mode)
        
        # Track error
        metrics_tracker.record_query(
            query=request.query,
            latency_ms=0,
            was_corrected=False,
            retrieval_score=0,
            cache_hit=False,
            error=True,
            mode=mode
        )
        
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query-stream")
async def query_stream(request: QueryRequest):
    """Query with streaming response"""
    try:
        mode = _normalize_mode(request.mode)
        conversation_id = _ensure_conversation(request.conversation_id, request.query)
        logger.info("query_stream_request", query=request.query, mode=mode, conversation_id=conversation_id)
        
        _maybe_update_conversation_title(conversation_id, request.query)
        chat_history_service.add_message(
            conversation_id,
            "user",
            request.query,
            metadata={"mode": mode}
        )
        conversation_history = _get_recent_history(conversation_id)
        
        async def generate():
            start_time = time.time()
            assistant_answer = ""
            metadata_block = {"conversation_id": conversation_id, "mode": mode}
            succeeded = False
            
            # Inform client about conversation context
            yield f"data: {json.dumps({'type': 'conversation', 'content': {'conversation_id': conversation_id}})}\n\n"
            
            try:
                if mode == "direct":
                    # Direct mode - LLM only with streaming
                    system_prompt = (
                        "You are a helpful assistant. Answer the user's question directly "
                        "without referencing uploaded documents."
                    )
                    history_prompt = _format_history_prompt(conversation_history)
                    prompt_parts = []
                    if history_prompt:
                        prompt_parts.append(f"Conversation history:\n{history_prompt}")
                    prompt_parts.append(f"User Question: {request.query}")
                    direct_prompt = "\n\n".join(prompt_parts)
                    
                    async for chunk in llm_service.generate_stream(direct_prompt, system_prompt=system_prompt):
                        assistant_answer += chunk
                        yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk, 'done': False})}\n\n"
                    
                    response_time_ms = (time.time() - start_time) * 1000
                    metadata_block.update({
                        "sources": [],
                        "retrieval_score": 0.0,
                        "response_time_ms": response_time_ms,
                        "was_corrected": False,
                        "correction_attempts": 0
                    })
                    yield f"data: {json.dumps({'type': 'metadata', 'content': metadata_block, 'done': True})}\n\n"
                    succeeded = True
                
                elif mode == "fast":
                    # Fast mode - RAG without correction, WITH streaming
                    async for chunk in rag_agent.run_stream(
                        request.query,
                        chat_history=conversation_history,
                        num_query_variations=1,
                        max_corrections=0  # NO CORRECTION
                    ):
                        if chunk.get("type") == "answer_chunk":
                            assistant_answer += chunk.get("content", "")
                        elif chunk.get("type") == "answer" and chunk.get("done"):
                            assistant_answer = chunk.get("content", "")
                        elif chunk.get("type") == "metadata":
                            metadata_block.update(chunk.get("content", {}))
                            chunk["content"] = metadata_block
                        
                        yield f"data: {json.dumps(chunk)}\n\n"
                    
                    if "response_time_ms" not in metadata_block:
                        metadata_block["response_time_ms"] = (time.time() - start_time) * 1000
                    if "sources" not in metadata_block:
                        metadata_block["sources"] = []
                    if "retrieval_score" not in metadata_block:
                        metadata_block["retrieval_score"] = 0.0
                    metadata_block.setdefault("was_corrected", False)
                    metadata_block.setdefault("correction_attempts", 0)
                    
                    succeeded = True
                
                else:  # quality mode
                    # Quality mode - Full RAG with correction, WITH streaming
                    async for chunk in rag_agent.run_stream(
                        request.query,
                        chat_history=conversation_history,
                        num_query_variations=settings.NUM_QUERY_VARIATIONS,
                        max_corrections=settings.MAX_CORRECTION_ATTEMPTS
                    ):
                        if chunk.get("type") == "answer_chunk":
                            assistant_answer += chunk.get("content", "")
                        elif chunk.get("type") == "answer" and chunk.get("done"):
                            assistant_answer = chunk.get("content", "")
                        elif chunk.get("type") == "metadata":
                            metadata_block.update(chunk.get("content", {}))
                            chunk["content"] = metadata_block
                        
                        yield f"data: {json.dumps(chunk)}\n\n"
                    
                    if "response_time_ms" not in metadata_block:
                        metadata_block["response_time_ms"] = (time.time() - start_time) * 1000
                    if "sources" not in metadata_block:
                        metadata_block["sources"] = []
                    if "retrieval_score" not in metadata_block:
                        metadata_block["retrieval_score"] = 0.0
                    metadata_block.setdefault("was_corrected", False)
                    metadata_block.setdefault("correction_attempts", 0)
                    
                    succeeded = True
            
            except Exception as e:
                logger.error("stream_error", error=str(e), mode=mode)
                
                metrics_tracker.record_query(
                    query=request.query,
                    latency_ms=(time.time() - start_time) * 1000,
                    was_corrected=False,
                    retrieval_score=0,
                    cache_hit=metadata_block.get("cache_hit", False),
                    error=True,
                    mode=mode
                )
                
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
                return
            
            if succeeded:
                if not assistant_answer:
                    assistant_answer = "I cannot find this information in the provided documents." if mode != "direct" else "I'm sorry, I couldn't generate a response."
                response_time_ms = metadata_block.get("response_time_ms", (time.time() - start_time) * 1000)
                chat_history_service.add_message(
                    conversation_id,
                    "assistant",
                    assistant_answer,
                    metadata={
                        **metadata_block,
                        "response_time_ms": response_time_ms
                    }
                )
                
                metrics_tracker.record_query(
                    query=request.query,
                    latency_ms=response_time_ms,
                    was_corrected=metadata_block.get("was_corrected", False),
                    retrieval_score=metadata_block.get("retrieval_score", 0.0),
                    cache_hit=metadata_block.get("cache_hit", False),
                    error=False,
                    mode=mode
                )
        
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
        
        # Index document
        result = vector_store.index_document(file_path)
        
        # CRITICAL: Rebuild BM25 for hybrid search
        vector_store._rebuild_bm25_index()
        logger.info("bm25_rebuilt_after_upload")
        
        # CRITICAL: Clear cache so new documents are immediately searchable
        cache_service.clear()
        logger.info("cache_cleared_after_upload")
        
        logger.info("upload_complete", 
                   filename=file.filename,
                   chunks=result["chunks"])
        
        return {
            "message": f"Document '{file.filename}' uploaded and indexed successfully",
            "filename": file.filename,
            "chunks": result["chunks"]
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

@router.get("/conversations")
async def list_conversations(limit: int = 50):
    """List saved conversations for the sidebar"""
    try:
        conversations = chat_history_service.get_all_conversations(limit=limit)
        return {"conversations": conversations}
    except Exception as e:
        logger.error("list_conversations_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/conversations")
async def create_conversation(title: str = "New Chat"):
    """Create a new empty conversation"""
    try:
        conversation_id = chat_history_service.create_conversation(title=title)
        logger.info("conversation_created_api", id=conversation_id, title=title)
        return {"conversation_id": conversation_id, "title": title}
    except Exception as e:
        logger.error("create_conversation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, limit: int = 100):
    """Fetch message history for a conversation"""
    try:
        messages = chat_history_service.get_conversation_history(conversation_id, limit=limit)
        return {"conversation_id": conversation_id, "messages": messages}
    except Exception as e:
        logger.error("conversation_history_error", id=conversation_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and its messages"""
    try:
        chat_history_service.delete_conversation(conversation_id)
        logger.info("conversation_deleted_api", id=conversation_id)
        return {"message": "Conversation deleted", "conversation_id": conversation_id}
    except Exception as e:
        logger.error("delete_conversation_error", id=conversation_id, error=str(e))
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
        
        # CRITICAL: Clear cache and rebuild indexes
        cache_service.clear()
        logger.info("cache_cleared_after_delete")
        
        # Rebuild BM25 index
        vector_store._rebuild_bm25_index()
        logger.info("bm25_rebuilt_after_delete")
        
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
@router.post("/cache/clear")
async def clear_cache():
    """Clear all cache"""
    cache_service.clear()
    logger.info("cache_cleared_manually")
    return {"message": "Cache cleared"}
@router.post("/evaluation/run")
async def run_evaluation(n_questions: int = 20, test_cases: list = None):
    """Run RAGAS evaluation to measure RAG system quality"""
    try:
        logger.info("run_evaluation_request")
        
        # If no test cases provided, generate them
        #if not test_cases:
        test_cases = await ragas_evaluator.generate_test_dataset(n_questions)
        
        # Run evaluation
        results = await ragas_evaluator.evaluate_system(test_cases)
        
        logger.info("run_evaluation_complete")
        formatted_results = {
        "avg_faithfulness": results.get("avg_faithfulness", 0), 
        "avg_relevancy": results.get("avg_relevancy", 0),
        "avg_recall": results.get("avg_recall", 0), 
        "num_cases": len(test_cases)
        }
        
        # Add explanations
        explanation = {
            "faithfulness": "Measures if the answer is grounded in the retrieved context (0-1, higher is better)",
            "answer_relevancy": "Measures if the answer addresses the question (0-1, higher is better)",
            "context_recall": "Measures if all relevant info was retrieved (0-1, higher is better)",
            "context_precision": "Measures ranking quality of retrieved docs (0-1, higher is better)"
        }
        
        return {
            "message": "Evaluation complete",
            "results": formatted_results,
            "explanation": explanation
        }
        
    except Exception as e:
        logger.error("run_evaluation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))