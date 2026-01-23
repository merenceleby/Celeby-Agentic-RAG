import httpx
from config import settings
import structlog
import json
from typing import AsyncGenerator

logger = structlog.get_logger()

class LLMService:
    """Ollama LLM service with streaming support"""
    
    def __init__(self):
        self.base_url = settings.OLLAMA_HOST
        self.model = settings.OLLAMA_MODEL
        logger.info("llm_service_init",
                   host=self.base_url,
                   model=self.model)
    
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate completion (non-streaming)"""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                logger.info("llm_generate",
                           prompt_length=len(prompt),
                           response_length=len(result["response"]))
                
                return result["response"]
        except Exception as e:
            logger.error("llm_generate_error", error=str(e))
            raise
    
    async def generate_stream(self, prompt: str, system_prompt: str = None) -> AsyncGenerator[str, None]:
        """Generate completion with streaming"""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
        except Exception as e:
            logger.error("llm_stream_error", error=str(e))
            raise
    
    async def check_answer_quality(self, question: str, answer: str, context: str) -> dict:
        """Validate answer quality against context"""
        prompt = f"""Given this context:
{context}

Question: {question}
Answer: {answer}

Evaluate if this answer is accurate and well-supported by the context.
Respond ONLY with valid JSON in this exact format:
{{"is_correct": true, "reason": "explanation here"}}
or
{{"is_correct": false, "reason": "explanation here"}}"""
        
        response = await self.generate(prompt)
        
        try:
            # Clean response and extract JSON
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
            logger.warning("answer_quality_parse_error",
                          error=str(e),
                          response=response[:200])
            return {"is_correct": True, "reason": "Unable to parse validation"}

# Singleton instance
llm_service = LLMService()