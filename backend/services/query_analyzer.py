from services.llm import llm_service
import structlog
import json

logger = structlog.get_logger()

class QueryAnalyzer:
    """Analyze and classify user queries"""
    
    async def analyze_query(self, query: str) -> dict:
        """
        Analyze query type and characteristics
        
        Returns:
            dict: Query analysis including type, complexity, entities
        """
        prompt = f"""Analyze this user query and provide classification.

Query: {query}

Respond ONLY with valid JSON in this exact format:
{{
    "type": "factual|comparison|procedural|opinion|exploratory",
    "complexity": "simple|medium|complex",
    "requires_multi_hop": true/false,
    "key_entities": ["entity1", "entity2"],
    "intent": "brief description of user intent"
}}

Classification:"""
        
        response = await llm_service.generate(prompt)
        
        try:
            # Clean response
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
            
            analysis = json.loads(cleaned)
            
            logger.info("query_analysis",
                       query=query[:50],
                       type=analysis.get("type"),
                       complexity=analysis.get("complexity"))
            
            return analysis
        except Exception as e:
            logger.warning("query_analysis_parse_error",
                          error=str(e),
                          response=response[:200])
            
            # Return default analysis
            return {
                "type": "factual",
                "complexity": "medium",
                "requires_multi_hop": False,
                "key_entities": [],
                "intent": "Answer user question"
            }

# Singleton instance
query_analyzer = QueryAnalyzer()