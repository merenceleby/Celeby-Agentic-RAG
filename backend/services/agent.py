from typing import TypedDict, List, AsyncGenerator
from langgraph.graph import StateGraph, END
from services.llm import llm_service
from services.vector_store import vector_store
from services.reranker import reranker_service
from services.cache import cache_service
from config import settings
import structlog
import time
import json

logger = structlog.get_logger()

class AgentState(TypedDict):
    query: str
    rewritten_queries: List[str]
    retrieved_docs: List[str]
    ranked_docs: List[str]
    answer: str
    correction_attempts: int
    is_correct: bool
    correction_reason: str
    retrieval_score: float
    start_time: float
    metadata: dict

class RAGAgent:
    """Self-correcting RAG agent with LangGraph"""
    
    def __init__(self):
        self.graph = self._build_graph()
        logger.info("rag_agent_init", status="ready")
    
    def _build_graph(self):
        """Build LangGraph workflow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("rewrite_query", self._rewrite_query)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("rerank", self._rerank)
        workflow.add_node("generate", self._generate)
        workflow.add_node("validate", self._validate)
        
        # Define edges
        workflow.set_entry_point("rewrite_query")
        workflow.add_edge("rewrite_query", "retrieve")
        workflow.add_edge("retrieve", "rerank")
        workflow.add_edge("rerank", "generate")
        workflow.add_edge("generate", "validate")
        
        # Conditional edge for self-correction
        workflow.add_conditional_edges(
            "validate",
            self._should_correct,
            {
                "correct_again": "rewrite_query",
                "finish": END
            }
        )
        
        return workflow.compile()
    
    async def _rewrite_query(self, state: AgentState) -> AgentState:
        """Rewrite query into multiple variations"""
        logger.info("agent_step", step="rewrite_query", query=state['query'])
        
        prompt = f"""Rewrite this query into {settings.NUM_QUERY_VARIATIONS} different variations to improve document retrieval.
Each variation should capture different aspects or phrasings of the question.

Original Query: {state['query']}

Provide {settings.NUM_QUERY_VARIATIONS} variations, one per line, without numbering or bullets:"""
        
        response = await llm_service.generate(prompt)
        queries = [q.strip() for q in response.split('\n') if q.strip()]
        queries = queries[:settings.NUM_QUERY_VARIATIONS]
        
        # Add original query
        if state['query'] not in queries:
            queries.insert(0, state['query'])
        
        state["rewritten_queries"] = queries
        
        logger.info("query_rewrite_complete", num_queries=len(queries))
        
        return state
    
    async def _retrieve(self, state: AgentState) -> AgentState:
        """Retrieve documents using hybrid search"""
        logger.info("agent_step", step="retrieve")
        
        # Check cache first
        cache_key = cache_service._generate_key("retrieval", state['query'])
        cached_docs = cache_service.get(cache_key)
        
        if cached_docs:
            state["retrieved_docs"] = cached_docs
            logger.info("retrieval_cache_hit")
            return state
        
        all_docs = set()
        
        # Retrieve for each query variation
        for query in state["rewritten_queries"]:
            results = vector_store.hybrid_search(query, top_k=settings.TOP_K_RETRIEVAL // len(state["rewritten_queries"]))
            all_docs.update(results["documents"])
        
        # Convert to list and limit
        unique_docs = list(all_docs)[:settings.TOP_K_RETRIEVAL]
        state["retrieved_docs"] = unique_docs
        
        # Cache the results
        cache_service.set(cache_key, unique_docs)
        
        logger.info("retrieval_complete", num_docs=len(unique_docs))
        
        return state
    
    async def _rerank(self, state: AgentState) -> AgentState:
        """Re-rank documents using cross-encoder"""
        logger.info("agent_step", step="rerank")
        
        if not state["retrieved_docs"]:
            logger.warning("no_documents_to_rerank")
            state["ranked_docs"] = []
            state["retrieval_score"] = 0.0
            return state
        
        # Re-rank using cross-encoder
        ranked = reranker_service.rerank(
            state["query"],
            state["retrieved_docs"],
            top_k=settings.TOP_K_RERANK
        )
        
        state["ranked_docs"] = [doc for doc, score in ranked]
        state["retrieval_score"] = float(ranked[0][1]) if ranked else 0.0
        
        logger.info("rerank_complete",
                   num_docs=len(state["ranked_docs"]),
                   top_score=state["retrieval_score"])
        
        return state
    
    async def _generate(self, state: AgentState) -> AgentState:
        """Generate answer from retrieved context"""
        logger.info("agent_step", step="generate")
        
        if not state["ranked_docs"]:
            state["answer"] = "I couldn't find relevant information to answer your question."
            return state
        
        context = "\n\n".join(state["ranked_docs"])
        
        system_prompt = """You are a precise document assistant. Your ONLY job is to answer questions based on the provided context.

STRICT RULES:
1. If the answer is NOT in the context, you MUST respond: "I cannot find this information in the provided documents."
2. NEVER use your general knowledge or training data.
3. NEVER make assumptions or inferences beyond what's explicitly stated.
4. If unsure, say you cannot find the information."""
        
        prompt = f"""Context from documents:
{context}

Question: {state['query']}

Answer based ONLY on the context above (follow the strict rules):"""
        
        answer = await llm_service.generate(prompt, system_prompt=system_prompt)
        state["answer"] = answer.strip()
        
        logger.info("generation_complete", answer_length=len(answer))
        
        return state
    
    async def _validate(self, state: AgentState) -> AgentState:
        """Validate answer quality"""
        logger.info("agent_step", step="validate")
        
        if not state["ranked_docs"]:
            state["is_correct"] = False
            state["correction_reason"] = "No documents retrieved"
            return state
        
        context = "\n\n".join(state["ranked_docs"])
        
        # First check: Is the answer actually in the context?
        check_prompt = f"""Does the following context contain information to answer this question?

Context:
{context[:1000]}

Question: {state['query']}

Respond with ONLY "YES" or "NO":"""
        
        context_check = await llm_service.generate(check_prompt)
        
        if "NO" in context_check.upper():
            state["answer"] = "I cannot find this information in the provided documents."
            state["is_correct"] = True  # Don't retry, this is correct behavior
            state["correction_reason"] = "Information not in documents"
            logger.info("validation_no_info_in_docs", query=state['query'])
            return state
        
        # Second check: Quality validation
        validation = await llm_service.check_answer_quality(
            state["query"],
            state["answer"],
            context
        )
        
        state["is_correct"] = validation.get("is_correct", True)
        state["correction_reason"] = validation.get("reason", "")
        
        if not state["is_correct"]:
            state["correction_attempts"] = state.get("correction_attempts", 0) + 1
            logger.info("validation_failed",
                       attempts=state["correction_attempts"],
                       reason=state["correction_reason"])
        else:
            logger.info("validation_passed")
        
        return state
    
    def _should_correct(self, state: AgentState) -> str:
        """Decide whether to attempt correction"""
        if state.get("is_correct", True):
            return "finish"
        
        if state.get("correction_attempts", 0) >= settings.MAX_CORRECTION_ATTEMPTS:
            logger.info("max_corrections_reached")
            return "finish"
        
        logger.info("attempting_correction",
                   attempt=state.get("correction_attempts", 0))
        return "correct_again"
    
    async def run(self, query: str) -> dict:
        """Run the agent"""
        start_time = time.time()
        
        initial_state = {
            "query": query,
            "rewritten_queries": [],
            "retrieved_docs": [],
            "ranked_docs": [],
            "answer": "",
            "correction_attempts": 0,
            "is_correct": False,
            "correction_reason": "",
            "retrieval_score": 0.0,
            "start_time": start_time,
            "metadata": {}
        }
        
        logger.info("agent_run_start", query=query)
        
        final_state = await self.graph.ainvoke(initial_state)
        
        response_time = (time.time() - start_time) * 1000  # ms
        
        logger.info("agent_run_complete",
                   query=query,
                   response_time_ms=response_time,
                   correction_attempts=final_state["correction_attempts"],
                   was_corrected=final_state["correction_attempts"] > 0)
        
        return {
            "answer": final_state["answer"],
            "sources": final_state["ranked_docs"],
            "correction_attempts": final_state["correction_attempts"],
            "was_corrected": final_state["correction_attempts"] > 0,
            "retrieval_score": final_state["retrieval_score"],
            "response_time_ms": response_time,
            "metadata": {
                "num_rewritten_queries": len(final_state["rewritten_queries"]),
                "num_retrieved_docs": len(final_state["retrieved_docs"]),
                "num_ranked_docs": len(final_state["ranked_docs"])
            }
        }
    
    async def run_stream(self, query: str) -> AsyncGenerator[dict, None]:
        """Run agent with streaming response"""
        start_time = time.time()
        
        # Run retrieval and reranking first
        initial_state = {
            "query": query,
            "rewritten_queries": [],
            "retrieved_docs": [],
            "ranked_docs": [],
            "answer": "",
            "correction_attempts": 0,
            "is_correct": False,
            "correction_reason": "",
            "retrieval_score": 0.0,
            "start_time": start_time,
            "metadata": {}
        }
        
        # Execute up to generation
        state = await self._rewrite_query(initial_state)
        state = await self._retrieve(state)
        state = await self._rerank(state)
        
        # Stream generation
        if not state["ranked_docs"]:
            yield {
                "type": "answer",
                "content": "I couldn't find relevant information to answer your question.",
                "done": True
            }
            return
        
        context = "\n\n".join(state["ranked_docs"])
        
        prompt = f"""Based on the following context, answer the question accurately and concisely.

Context:
{context}

Question: {state['query']}

Answer:"""
        
        # Stream the answer
        async for chunk in llm_service.generate_stream(prompt):
            yield {
                "type": "answer_chunk",
                "content": chunk,
                "done": False
            }
        
        # Final metadata
        response_time = (time.time() - start_time) * 1000
        
        yield {
            "type": "metadata",
            "content": {
                "sources": state["ranked_docs"],
                "retrieval_score": state["retrieval_score"],
                "response_time_ms": response_time
            },
            "done": True
        }

# Singleton instance
rag_agent = RAGAgent()