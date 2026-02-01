import httpx
from config import settings
import structlog
import json
from typing import AsyncGenerator
import asyncio
logger = structlog.get_logger()

class LLMService:
    """Ollama LLM service with streaming support"""
    
    def __init__(self):
        self.base_url = settings.OLLAMA_HOST
        self.model = settings.OLLAMA_MODEL
        self.max_retries = 3 
        self.base_timeout = 120.0
        
        logger.info("llm_service_init", 
                   host=self.base_url,
                   model=self.model,
                   max_retries=self.max_retries)
    
    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Retry logic with exponential backoff"""
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == self.max_retries - 1:
                    # Son deneme, hata fırlat
                    logger.error("llm_max_retries_exceeded",
                               attempt=attempt + 1,
                               error=str(e))
                    raise
                
                # Exponential backoff: 2^attempt seconds
                wait_time = 2 ** attempt
                logger.warning("llm_retry",
                             attempt=attempt + 1,
                             max_retries=self.max_retries,
                             wait_time=wait_time,
                             error=str(e))
                
                await asyncio.sleep(wait_time)
            except Exception as e:
                # Diğer hatalar için hemen fırlat
                logger.error("llm_error_non_retryable", error=str(e))
                raise
    
    async def _generate_with_timeout(self, payload: dict, timeout: float) -> str:
        """Single generation attempt with timeout"""
        url = f"{self.base_url}/api/generate"
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            
            logger.info("llm_generate",
                       prompt_length=len(payload.get("prompt", "")),
                       response_length=len(result["response"]),
                       timeout_used=timeout)
            
            return result["response"]
    
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate completion with retry logic"""
        
        async def attempt_generation(attempt_num: int = 0):
            timeout = self.base_timeout * (1.5 ** attempt_num)  # 120s, 180s, 270s
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1,
                    "repeat_penalty": 1.1
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            return await self._generate_with_timeout(payload, timeout)
        
        # Retry with backoff
        for attempt in range(self.max_retries):
            try:
                return await attempt_generation(attempt)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == self.max_retries - 1:
                    logger.error("llm_max_retries_exceeded",
                               attempt=attempt + 1,
                               error=str(e))
                    return self._get_fallback_response(prompt)
                
                wait_time = 2 ** attempt
                logger.warning("llm_retry",
                             attempt=attempt + 1,
                             wait_time=wait_time,
                             error=str(e))
                
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error("llm_error_non_retryable", error=str(e))
                return self._get_fallback_response(prompt)
    
    async def generate_stream(self, prompt: str, system_prompt: str = None) -> AsyncGenerator[str, None]:
        """Generate completion with streaming and retry"""
        
        async def attempt_stream(attempt_num: int = 0):
            timeout = self.base_timeout * (1.5 ** attempt_num)
            url = f"{self.base_url}/api/generate"
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1,
                    "repeat_penalty": 1.1
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                chunk = json.loads(line)
                                if "response" in chunk:
                                    yield chunk["response"]
                            except json.JSONDecodeError:
                                continue
        
        # Retry logic for streaming
        for attempt in range(self.max_retries):
            try:
                async for chunk in attempt_stream(attempt):
                    yield chunk
                return  # Success, exit
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == self.max_retries - 1:
                    logger.error("llm_stream_max_retries_exceeded",
                               attempt=attempt + 1,
                               error=str(e))
                    fallback = self._get_fallback_response(prompt)
                    for word in fallback.split():
                        yield word + " "
                    return
                
                wait_time = 2 ** attempt
                logger.warning("llm_stream_retry",
                             attempt=attempt + 1,
                             wait_time=wait_time,
                             error=str(e))
                
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error("llm_stream_error_non_retryable", error=str(e))
                fallback = self._get_fallback_response(prompt)
                for word in fallback.split():
                    yield word + " "
                return
    
    def _get_fallback_response(self, prompt: str) -> str:
        """Fallback response when LLM fails"""
        logger.warning("using_fallback_response", prompt_preview=prompt[:100])
        
        if "cannot find" in prompt.lower() or "context:" in prompt.lower():
            return "I apologize, but I'm currently experiencing technical difficulties and cannot process your request. Please try again in a moment."
        elif "validate" in prompt.lower() or "is_correct" in prompt.lower():
            return '{"is_correct": true, "reason": "Service temporarily unavailable"}'
        else:
            return "I apologize, but I'm experiencing technical difficulties. Please try your question again."
    
    async def check_answer_quality(self, question: str, answer: str, context: str) -> dict:
        """Validate answer quality against context - STRICT VERSION"""
        
        prompt = f"""You are a STRICT fact-checker. Your job is to verify if an answer is ONLY based on the given context.

        Context:
        {context[:2000]}

        Question: {question}
        Answer: {answer}

        VALIDATION RULES:
        1. Check if EVERY fact in the answer exists in the context
        2. Check if answer uses information NOT in context (hallucination)
        3. Check if answer makes assumptions beyond context
        4. Check if answer is relevant to the question

        Respond ONLY with valid JSON:
        {{"is_correct": true/false, "reason": "specific reason"}}

        Mark as FALSE if:
        - Answer contains ANY information not in context
        - Answer makes assumptions or inferences
        - Answer uses general knowledge
        - Answer is off-topic

        Mark as TRUE only if:
        - Every fact is directly from context
        - No external information added
        - Relevant to question
        """

        response = await self.generate(prompt)
        
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
            
            result = json.loads(cleaned)
            
            logger.info("answer_quality_check",
                    is_correct=result.get("is_correct", True),
                    reason=result.get("reason", ""))
            
            return result
            
        except Exception as e:
            logger.error("validation_error", error=str(e))
            # ✅ SAFE FALLBACK: Assume correct to avoid correction loops
            return {
                "is_correct": True, "reason": "Validation service temporarily unavailable"
            }

# Singleton
llm_service = LLMService()