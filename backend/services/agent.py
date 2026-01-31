import time
import structlog
from typing import List, Dict, Any, AsyncGenerator
from langgraph.graph import StateGraph, END
from services.llm import llm_service
from services.vector_store import vector_store
from services.reranker import reranker_service
from services.cache import cache_service
from config import settings

logger = structlog.get_logger()

class AgentState(Dict):
    """State for RAG agent"""
    pass

class RAGAgent:
    """Self-correcting RAG agent with LangGraph"""
    
    def __init__(self):
        self.graph = self._build_graph()
        logger.info("rag_agent_init", status="ready")
    
    def _build_graph(self):
        """Build LangGraph workflow"""
        #workflow = StateGraph(AgentState)
        workflow = StateGraph(dict)
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
        desired_variations = state.get("num_query_variations", settings.NUM_QUERY_VARIATIONS)
        if desired_variations < 1:
            desired_variations = 1
        
        # If only 1 variation requested (fast mode), skip rewriting
        if desired_variations == 1:
            state["rewritten_queries"] = [state['query']]
            logger.info("query_rewrite_skipped", reason="single_variation")
            return state
        
        prompt = f"""Rewrite this query into {desired_variations} different variations to improve document retrieval.
Each variation should capture different aspects or phrasings of the question.

Original Query: {state['query']}

Provide {desired_variations} variations, one per line, without numbering or bullets:"""
        
        response = await llm_service.generate(prompt)
        queries = [q.strip() for q in response.split('\n') if q.strip()]
        queries = queries[:desired_variations]
        
        # Add original query
        if state['query'] not in queries:
            queries.insert(0, state['query'])
        
        state["rewritten_queries"] = queries
        
        logger.info("query_rewrite_complete", num_queries=len(queries))
        
        return state
    
    async def _retrieve(self, state: AgentState) -> AgentState:
        """Retrieve documents using hybrid search with parallel queries"""
        logger.info("agent_step", step="retrieve")
        
        # Check cache first
        cache_key = cache_service._generate_key("retrieval", state['query'])
        cached_docs = cache_service.get(cache_key)
        
        if cached_docs:
            state["retrieved_docs"] = cached_docs
            state["cache_hit"] = True
            logger.info("retrieval_cache_hit")
            return state
        state["cache_hit"] = False
        all_docs = set()
        
        # Parallel retrieval for each query variation
        import asyncio
        
        async def retrieve_single(query):
            return vector_store.hybrid_search(query, top_k=settings.TOP_K_RETRIEVAL)
        
        # Run all queries in parallel
        results = await asyncio.gather(*[retrieve_single(q) for q in state["rewritten_queries"]])
        
        for result in results:
            all_docs.update(result["documents"])
        
        # Convert to list and limit
        unique_docs = list(all_docs)[:settings.TOP_K_RETRIEVAL]
        state["retrieved_docs"] = unique_docs
        
        # Cache the results
        cache_service.set(cache_key, unique_docs)
        
        logger.info("retrieval_complete", 
                   num_docs=len(unique_docs),
                   parallel_queries=len(state["rewritten_queries"]))
        
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
            top_k=settings.TOP_K_RERANK,
            threshold=-5.0
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
        
        history_context = self._format_history_context(state.get("chat_history"))
        if not state["ranked_docs"] and not history_context:
            state["answer"] = "I couldn't find relevant information to answer your question."
            return state
        
        context_sections = []
        if history_context:
            context_sections.append(history_context)
        if state["ranked_docs"]:
            context_sections.append("Document excerpts:\n" + "\n\n".join(state["ranked_docs"]))
        context = "\n".join(context_sections)

        system_prompt = """You are a STRICT document Q&A system. You MUST follow these rules:

        CRITICAL RULES:
        1. ONLY use information from the Context below
        2. If answer is NOT in Context, respond EXACTLY: "I cannot find this information in the provided documents."
        3. NEVER add information from your training data
        4. NEVER make assumptions or inferences
        5. NEVER say "based on my knowledge" or similar phrases
        6. If unsure, say you cannot find the information

        OUTPUT FORMAT:
        - Direct answer first
        - Use facts from context word-for-word when possible
        - Keep it concise
        - No preamble like "Based on the context..."
        """

        prompt = f"""Context from documents:
        {context}

        User Question: {state['query']}

        Remember: Answer ONLY from the context above. If you cannot find the answer, say "I cannot find this information in the provided documents."

        Answer:"""

        system_prompt2 = """You are a PRECISE document Q&A assistant.

        STRICT RULES:
        1. Answer ONLY from the provided context
        2. If info is NOT in context, say: "I cannot find this information in the provided documents."
        3. NEVER use general knowledge
        4. Quote specific facts when possible
        5. Be concise but complete
        6. Follow user's formatting requests (bullet points, short answer, etc.)

        Context quality indicators:
        - If context is unclear or contradictory, say so
        - If context is partial, acknowledge limitations
        """      
        prompt = f"""Context from documents:
{context}

User Question: {state['query']}

Answer based ONLY on the context above. Follow the strict rules AND respect any formatting requests in the user's question:"""
        
        answer = await llm_service.generate(prompt, system_prompt=system_prompt)
        state["answer"] = answer.strip()
        
        logger.info("generation_complete", answer_length=len(answer))
        
        return state
    


   
    def _should_correct(self, state: AgentState) -> str:
        """Decide whether to attempt correction"""
        if state.get("is_correct", True):
            return "finish"
        
        max_corrections = state.get("max_corrections", settings.MAX_CORRECTION_ATTEMPTS)
        if state.get("correction_attempts", 0) >= max_corrections:
            logger.info("max_corrections_reached")
            return "finish"
        
        logger.info("attempting_correction",
                   attempt=state.get("correction_attempts", 0))
        return "correct_again"
    
    def _format_history_context(self, history: List[Dict[str, Any]] | None) -> str:
        if not history:
            return ""
        trimmed = history[-10:]
        segments = []
        for item in trimmed:
            role = "User" if item.get("role") == "user" else "Assistant"
            content = item.get("content", "").strip()
            if content:
                segments.append(f"{role}: {content}")
        if not segments:
            return ""
        return "Conversation history:\n" + "\n".join(segments) + "\n\n"
    
    def _combine_context(self, ranked_docs: List[str], history: List[Dict[str, Any]] | None) -> str:
        parts: List[str] = []
        history_context = self._format_history_context(history)
        if history_context:
            parts.append(history_context.strip())
        if ranked_docs:
            parts.append("Document excerpts:\n" + "\n\n".join(ranked_docs))
        return "\n\n".join(parts).strip()
    
    async def run(self, 
                  query: str, 
                  chat_history: List[Dict[str, Any]] | None = None,
                  max_corrections: int | None = None,
                  num_query_variations: int | None = None) -> dict:
        """Run the agent with full quality mode (self-correction enabled)"""
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
            "metadata": {},
            "chat_history": chat_history or [],
            "max_corrections": max_corrections if max_corrections is not None else settings.MAX_CORRECTION_ATTEMPTS,
            "num_query_variations": num_query_variations if num_query_variations is not None else settings.NUM_QUERY_VARIATIONS,
            "cache_hit": False
            
        }
        
        logger.info("agent_run_start", query=query, mode="quality")
        
        final_state = await self.graph.ainvoke(initial_state)
        
        response_time = (time.time() - start_time) * 1000  # ms
        
        logger.info("agent_run_complete",
                   query=query,
                   response_time_ms=response_time,
                   correction_attempts=final_state["correction_attempts"],
                   was_corrected=final_state["correction_attempts"] > 0,
                   cache_hit=final_state.get("cache_hit", False))
        
        return {
            "answer": final_state["answer"],
            "sources": final_state["ranked_docs"],
            "correction_attempts": final_state["correction_attempts"],
            "was_corrected": final_state["correction_attempts"] > 0,
            "retrieval_score": final_state["retrieval_score"],
            "response_time_ms": response_time,
            "cache_hit": final_state.get("cache_hit", False), 
            "metadata": {
                "num_rewritten_queries": len(final_state["rewritten_queries"]),
                "num_retrieved_docs": len(final_state["retrieved_docs"]),
                "num_ranked_docs": len(final_state["ranked_docs"]),
                "cache_hit": final_state.get("cache_hit", False), 
            }
        }
    
    async def run_fast(self, 
                       query: str,
                       chat_history: List[Dict[str, Any]] | None = None,
                       num_query_variations: int = 1) -> dict:
        """Run agent in fast mode (no self-correction, single query)"""
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
            "metadata": {},
            "chat_history": chat_history or [],
            "max_corrections": 0,  # NO SELF-CORRECTION IN FAST MODE
            "num_query_variations": 1  # SINGLE QUERY ONLY
        }
        
        logger.info("agent_run_start", query=query, mode="fast")
        
        final_state = await self.graph.ainvoke(initial_state)
        
        response_time = (time.time() - start_time) * 1000  # ms
        
        logger.info("agent_run_complete",
                   query=query,
                   mode="fast",
                   response_time_ms=response_time,
                   correction_attempts=0,
                   was_corrected=False)
        
        return {
            "answer": final_state["answer"],
            "sources": final_state["ranked_docs"],
            "correction_attempts": 0,
            "was_corrected": False,
            "retrieval_score": final_state["retrieval_score"],
            "response_time_ms": response_time,
            "metadata": {
                "num_rewritten_queries": 1,
                "num_retrieved_docs": len(final_state["retrieved_docs"]),
                "num_ranked_docs": len(final_state["ranked_docs"])
            }
        }
    
    async def run_stream(self, 
                         query: str,
                         chat_history: List[Dict[str, Any]] | None = None,
                         num_query_variations: int | None = None,
                         max_corrections: int = 0) -> AsyncGenerator[dict, None]:
        """Run agent with streaming response (used for both fast and quality modes)"""
        start_time = time.time()
        
        # Determine if this is fast mode or quality mode
        is_fast_mode = max_corrections == 0
        actual_variations = 1 if is_fast_mode else (num_query_variations or settings.NUM_QUERY_VARIATIONS)
        
        # Signal mode start
        yield {
            "type": "status",
            "content": f"Starting {'fast' if is_fast_mode else 'quality'} mode...",
            "done": False
        }
        
        # Run retrieval and reranking first (non-streaming part)
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
            "metadata": {},
            "chat_history": chat_history or [],
            "max_corrections": max_corrections,
            "num_query_variations": actual_variations
        }
        
        # Step 1: Rewrite query
        yield {"type": "status", "content": "Rewriting query...", "done": False}
        state = await self._rewrite_query(initial_state)
        
        # Step 2: Retrieve documents
        yield {"type": "status", "content": "Retrieving documents...", "done": False}
        state = await self._retrieve(state)
        
        # Step 3: Rerank
        yield {"type": "status", "content": "Reranking results...", "done": False}
        state = await self._rerank(state)
        
        # Step 4: Generate answer with streaming
        yield {"type": "status", "content": "Generating answer...", "done": False}
        
        history_context = self._format_history_context(state.get("chat_history"))
        if not state["ranked_docs"] and not history_context:
            answer = "I couldn't find relevant information to answer your question."
            yield {"type": "answer", "content": answer, "done": True}
        else:
            context_sections = []
            if history_context:
                context_sections.append(history_context)
            if state["ranked_docs"]:
                context_sections.append("Document excerpts:\n" + "\n\n".join(state["ranked_docs"]))
            context = "\n".join(context_sections)
            
            system_prompt = """You are a precise document assistant. Your ONLY job is to answer questions based on the provided context.

STRICT RULES:
1. If the answer is NOT in the context, you MUST respond: "I cannot find this information in the provided documents."
2. NEVER use your general knowledge or training data.
3. NEVER make assumptions or inferences beyond what's explicitly stated.
4. If unsure, say you cannot find the information.
5. ALWAYS follow user's formatting instructions (e.g., "in 1 sentence", "as a list", etc.)"""
            
            prompt = f"""Context from documents:
{context}

User Question: {state['query']}

Answer based ONLY on the context above:"""
            
            # Stream the answer
            full_answer = ""
            async for chunk in llm_service.generate_stream(prompt, system_prompt=system_prompt):
                full_answer += chunk
                yield {"type": "answer_chunk", "content": chunk, "done": False}
            
            yield {"type": "answer", "content": full_answer, "done": True}
            state["answer"] = full_answer
        
        # Step 5: Validate (only if not fast mode)
        if not is_fast_mode:
            yield {"type": "status", "content": "Validating answer...", "done": False}
            state = await self._validate(state)
            
            # If validation failed and we can correct, loop
            while not state.get("is_correct", True) and state.get("correction_attempts", 0) < max_corrections:
                yield {
                    "type": "correction",
                    "content": f"Attempting correction {state['correction_attempts']}...",
                    "done": False
                }
                
                # Re-run the full pipeline
                state = await self._rewrite_query(state)
                state = await self._retrieve(state)
                state = await self._rerank(state)
                state = await self._generate(state)
                
                # Stream corrected answer
                yield {"type": "answer", "content": state["answer"], "done": True}
                
                state = await self._validate(state)
        
        # Final metadata
        response_time = (time.time() - start_time) * 1000
        
        yield {
            "type": "metadata",
            "content": {
                "sources": state["ranked_docs"],
                "retrieval_score": state["retrieval_score"],
                "correction_attempts": state.get("correction_attempts", 0),
                "was_corrected": state.get("correction_attempts", 0) > 0,
                "response_time_ms": response_time,
                "mode": "fast" if is_fast_mode else "quality",
                "cache_hit": state.get("cache_hit", False)
            },
            "done": True
        }
    async def _validate(self, state: AgentState) -> AgentState:
        """Validate answer quality"""
        logger.info("agent_step", step="validate")
        
        # Skip validation if fast mode
        if state.get("max_corrections", 0) == 0:
            state["is_correct"] = True
            state["correction_reason"] = "Validation skipped (fast mode)"
            logger.info("validation_skipped", reason="fast_mode")
            return state
        
        # No documents → return "cannot find" message
        if not state["ranked_docs"]:
            state["answer"] = "I cannot find this information in the provided documents."
            state["is_correct"] = True
            state["correction_reason"] = "No documents - correct response"
            logger.info("validation_no_docs")
            return state
        
        # Answer already says "cannot find" → correct
        if "cannot find" in state["answer"].lower():
            state["is_correct"] = True
            state["correction_reason"] = "Correctly stated no information"
            logger.info("validation_passed", reason="cannot_find")
            return state
        
        # ✅ QUALITY CHECK WITH LLM
        context = "\n\n".join(state["ranked_docs"])
        
        try:
            validation = await llm_service.check_answer_quality(
                state["query"],
                state["answer"],
                context
            )
            
            state["is_correct"] = validation.get("is_correct", False)
            state["correction_reason"] = validation.get("reason", "")
            
            if not state["is_correct"]:
                state["correction_attempts"] = state.get("correction_attempts", 0) + 1
                logger.warning("validation_failed",
                            attempts=state["correction_attempts"],
                            reason=state["correction_reason"])
            else:
                logger.info("validation_passed")
            
        except Exception as e:
            # Validation failed → assume incorrect to trigger correction
            logger.error("validation_error", error=str(e))
            state["is_correct"] = False
            state["correction_reason"] = f"Validation error: {str(e)}"
            state["correction_attempts"] = state.get("correction_attempts", 0) + 1
        
        return state

# Singleton instance
rag_agent = RAGAgent()
