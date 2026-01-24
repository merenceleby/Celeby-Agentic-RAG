from services.llm import llm_service
from services.vector_store import vector_store
import structlog
import json
import random
from typing import List, Dict

logger = structlog.get_logger()

class RAGASEvaluator:
    """RAGAS-style evaluation for RAG systems"""
    
    async def generate_test_dataset(self, n_questions: int = 20) -> List[Dict]:
        """
        Generate synthetic test dataset from indexed documents
        
        Args:
            n_questions: Number of questions to generate
            
        Returns:
            List of test cases with question, ground_truth, context
        """
        logger.info("generating_test_dataset", n_questions=n_questions)
        
        all_docs = vector_store.get_all_documents()
        
        if not all_docs:
            logger.warning("no_documents_for_dataset_generation")
            return []
        
        # Sample random documents
        sample_size = min(n_questions, len(all_docs))
        sampled_docs = random.sample(all_docs, sample_size)
        
        dataset = []
        
        for idx, doc in enumerate(sampled_docs):
            try:
                qa_pair = await self._generate_qa_from_context(doc)
                
                if qa_pair:
                    dataset.append({
                        "question": qa_pair["question"],
                        "ground_truth": qa_pair["answer"],
                        "source_context": doc,
                        "id": f"test_{idx}"
                    })
                    
                    logger.info("test_case_generated", 
                               id=f"test_{idx}",
                               question=qa_pair["question"][:50])
            except Exception as e:
                logger.error("qa_generation_error", 
                            doc_preview=doc[:100],
                            error=str(e))
                continue
        
        logger.info("test_dataset_complete", total_cases=len(dataset))
        
        return dataset
    
    async def _generate_qa_from_context(self, context: str) -> dict:
        """Generate a question-answer pair from context"""
        prompt = f"""Based on the following text, generate a realistic question that can be answered from this text, and provide the ground truth answer.

Text:
{context}

Respond ONLY with valid JSON in this exact format:
{{
    "question": "A natural question someone might ask",
    "answer": "The accurate answer based on the text"
}}

JSON:"""
        
        response = await llm_service.generate(prompt)
        
        # Parse JSON
        cleaned = response.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        
        return json.loads(cleaned)
    
    async def evaluate_faithfulness(self, question: str, answer: str, context: str) -> float:
        """
        Evaluate if answer is faithful to the context
        
        Returns:
            Score between 0 and 1
        """
        prompt = f"""You are evaluating if an answer is faithful to the provided context.
An answer is faithful if EVERY claim in the answer can be verified from the context.

Context:
{context}

Question: {question}
Answer: {answer}

Evaluate STRICTLY:
- Check EACH statement in the answer
- Can EVERY statement be found in the context?
- Ignore minor rephrasing, focus on factual accuracy

Score 1.0: All claims are in context
Score 0.7-0.9: Most claims are in context
Score 0.4-0.6: Some claims are in context
Score 0.0-0.3: Most claims are NOT in context

Respond with ONLY a number between 0.0 and 1.0:"""
        
        response = await llm_service.generate(prompt)
        
        try:
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except:
            logger.warning("faithfulness_parse_error", response=response)
            return 0.5
    
    async def evaluate_answer_relevancy(self, question: str, answer: str) -> float:
        """
        Evaluate if answer is relevant to the question
        
        Returns:
            Score between 0 and 1
        """
        prompt = f"""Evaluate if the answer is relevant to the question.
A relevant answer directly addresses what was asked.

Question: {question}
Answer: {answer}

Respond with a score between 0.0 (not relevant) and 1.0 (highly relevant).
Respond ONLY with the number, nothing else.

Score:"""
        
        response = await llm_service.generate(prompt)
        
        try:
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except:
            logger.warning("relevancy_parse_error", response=response)
            return 0.5
    
    async def evaluate_context_recall(self, question: str, ground_truth: str, context: str) -> float:
        """
        Evaluate if the context contains information to answer the question
        
        Returns:
            Score between 0 and 1
        """
        prompt = f"""Evaluate if the context contains sufficient information to answer the question with the ground truth answer.

Question: {question}
Ground Truth Answer: {ground_truth}
Retrieved Context:
{context}

Respond with a score between 0.0 (context missing key info) and 1.0 (context has all needed info).
Respond ONLY with the number, nothing else.

Score:"""
        
        response = await llm_service.generate(prompt)
        
        try:
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except:
            logger.warning("recall_parse_error", response=response)
            return 0.5
    
    async def evaluate_system(self, test_cases: List[Dict], rag_system) -> Dict:
        """
        Evaluate RAG system on test cases
        
        Args:
            test_cases: List of test cases
            rag_system: RAG agent instance
            
        Returns:
            Evaluation metrics
        """
        logger.info("system_evaluation_start", num_cases=len(test_cases))
        
        results = {
            "faithfulness_scores": [],
            "relevancy_scores": [],
            "recall_scores": [],
            "cases": []
        }
        
        for case in test_cases:
            try:
                # Get system answer
                response = await rag_system.run(case["question"])
                
                # Evaluate
                faithfulness = await self.evaluate_faithfulness(
                    case["question"],
                    response["answer"],
                    "\n".join(response["sources"])
                )
                
                relevancy = await self.evaluate_answer_relevancy(
                    case["question"],
                    response["answer"]
                )
                
                recall = await self.evaluate_context_recall(
                    case["question"],
                    case["ground_truth"],
                    "\n".join(response["sources"])
                )
                
                results["faithfulness_scores"].append(faithfulness)
                results["relevancy_scores"].append(relevancy)
                results["recall_scores"].append(recall)
                
                results["cases"].append({
                    "question": case["question"],
                    "ground_truth": case["ground_truth"],
                    "system_answer": response["answer"],
                    "faithfulness": faithfulness,
                    "relevancy": relevancy,
                    "recall": recall
                })
                
                logger.info("case_evaluated",
                           question=case["question"][:50],
                           faithfulness=faithfulness,
                           relevancy=relevancy,
                           recall=recall)
                
            except Exception as e:
                logger.error("evaluation_error",
                            question=case["question"][:50],
                            error=str(e))
                continue
        
        # Calculate averages
        avg_faithfulness = sum(results["faithfulness_scores"]) / len(results["faithfulness_scores"]) if results["faithfulness_scores"] else 0
        avg_relevancy = sum(results["relevancy_scores"]) / len(results["relevancy_scores"]) if results["relevancy_scores"] else 0
        avg_recall = sum(results["recall_scores"]) / len(results["recall_scores"]) if results["recall_scores"] else 0
        
        summary = {
            "avg_faithfulness": avg_faithfulness,
            "avg_relevancy": avg_relevancy,
            "avg_recall": avg_recall,
            "num_cases": len(results["cases"]),
            "detailed_results": results["cases"]
        }
        
        logger.info("evaluation_complete",
                   avg_faithfulness=avg_faithfulness,
                   avg_relevancy=avg_relevancy,
                   avg_recall=avg_recall)
        
        return summary

# Singleton instance
ragas_evaluator = RAGASEvaluator()