from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from models import QueryRequest, QueryResponse, MetricsResponse
from services.agent import rag_agent
from services.vector_store import vector_store
from services.metrics import metrics_tracker
from services.query_analyzer import query_analyzer
from evaluation.ragas_eval import ragas_evaluator
import structlog
import json
import os

logger = structlog.get_logger()
router = APIRouter()

@router.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Query documents with RAG agent"""
    try:
        logger.info("query_request", query=request.query)
        
        # Analyze query (optional metadata)
        analysis = await query_analyzer.analyze_query(request.query)
        
        # Run agent
        result = await rag_agent.run(request.query)
        
        # Track metrics
        metrics_tracker.record_query(
            query=request.query,
            latency_ms=result["response_time_ms"],
            was_corrected=result["was_corrected"],
            retrieval_score=result["retrieval_score"],
            cache_hit=False,  # TODO: Track cache hits from agent
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
        
        async def generate():
            try:
                async for chunk in rag_agent.run_stream(request.query):
                    yield f"data: {json.dumps(chunk)}\n\n"
            except Exception as e:
                logger.error("stream_error", error=str(e))
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
    """Upload and index a PDF document"""
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
        
        # Process and index
        vector_store._process_pdf(file_path)
        
        logger.info("upload_complete", filename=file.filename)
        
        return {
            "message": f"Document '{file.filename}' uploaded and indexed successfully",
            "filename": file.filename
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

@router.post("/evaluation/generate-dataset")
async def generate_test_dataset(n_questions: int = 20):
    """Generate synthetic test dataset"""
    try:
        logger.info("generate_dataset_request", n_questions=n_questions)
        
        dataset = await ragas_evaluator.generate_test_dataset(n_questions)
        
        logger.info("generate_dataset_complete", num_cases=len(dataset))
        
        return {
            "message": f"Generated {len(dataset)} test cases",
            "dataset": dataset
        }
        
    except Exception as e:
        logger.error("generate_dataset_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluation/run")
async def run_evaluation(test_cases: list = None):
    """Run RAGAS evaluation on test cases"""
    try:
        logger.info("run_evaluation_request")
        
        # If no test cases provided, generate them
        if not test_cases:
            test_cases = await ragas_evaluator.generate_test_dataset(20)
        
        # Run evaluation
        results = await ragas_evaluator.evaluate_system(test_cases, rag_agent)
        
        logger.info("run_evaluation_complete")
        
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