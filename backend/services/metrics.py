from collections import defaultdict
import numpy as np
import structlog
from typing import Dict, List
import time

logger = structlog.get_logger()

class MetricsTracker:
    """Track and aggregate system metrics"""
    
    def __init__(self):
        self.queries: List[str] = []
        self.latencies: List[float] = []
        self.corrections: int = 0
        self.errors: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.retrieval_scores: List[float] = []
        self.start_time = time.time()
        
        logger.info("metrics_tracker_init", status="ready")
    
    def record_query(self, 
                     query: str,
                     latency_ms: float,
                     was_corrected: bool,
                     retrieval_score: float,
                     cache_hit: bool = False,
                     error: bool = False):
        """Record a query execution"""
        self.queries.append(query)
        self.latencies.append(latency_ms)
        self.retrieval_scores.append(retrieval_score)
        
        if was_corrected:
            self.corrections += 1
        
        if error:
            self.errors += 1
        
        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        
        logger.info("metric_recorded",
                   query=query[:50],
                   latency_ms=latency_ms,
                   was_corrected=was_corrected,
                   cache_hit=cache_hit)
    
    def get_metrics(self) -> Dict:
        """Get aggregated metrics"""
        total_queries = len(self.queries)
        
        if total_queries == 0:
            return {
                "total_queries": 0,
                "total_corrections": 0,
                "correction_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "error_rate": 0.0,
                "cache_hit_rate": 0.0,
                "avg_retrieval_score": 0.0,
                "uptime_seconds": time.time() - self.start_time
            }
        
        total_cache_requests = self.cache_hits + self.cache_misses
        
        return {
            "total_queries": total_queries,
            "total_corrections": self.corrections,
            "correction_rate": self.corrections / total_queries if total_queries > 0 else 0.0,
            "avg_latency_ms": np.mean(self.latencies) if self.latencies else 0.0,
            "p95_latency_ms": np.percentile(self.latencies, 95) if self.latencies else 0.0,
            "p99_latency_ms": np.percentile(self.latencies, 99) if self.latencies else 0.0,
            "error_rate": self.errors / total_queries if total_queries > 0 else 0.0,
            "cache_hit_rate": self.cache_hits / total_cache_requests if total_cache_requests > 0 else 0.0,
            "avg_retrieval_score": np.mean(self.retrieval_scores) if self.retrieval_scores else 0.0,
            "uptime_seconds": time.time() - self.start_time
        }
    
    def reset(self):
        """Reset all metrics"""
        self.queries = []
        self.latencies = []
        self.corrections = 0
        self.errors = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.retrieval_scores = []
        self.start_time = time.time()
        
        logger.info("metrics_reset")

# Singleton instance
metrics_tracker = MetricsTracker()