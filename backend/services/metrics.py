import os
import sqlite3
import structlog
import time
from typing import Dict, List

import numpy as np
from config import settings

logger = structlog.get_logger()


class MetricsTracker:
    """Track and aggregate system metrics with SQLite persistence"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.METRICS_DB_PATH
        self.start_time = time.time()
        self._ensure_directory()
        self._init_db()
        logger.info("metrics_tracker_init", db_path=self.db_path)

    def _ensure_directory(self):
        directory = os.path.dirname(self.db_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS query_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                latency_ms REAL,
                was_corrected INTEGER DEFAULT 0,
                retrieval_score REAL,
                cache_hit INTEGER DEFAULT 0,
                error INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()
        logger.info("metrics_db_initialized")

    def record_query(
        self,
        query: str,
        latency_ms: float,
        was_corrected: bool,
        retrieval_score: float,
        cache_hit: bool = False,
        error: bool = False,
        mode: str = "fast",
    ):
        """Persist a query execution snapshot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO query_metrics
            (query, mode, latency_ms, was_corrected, retrieval_score, cache_hit, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query,
                mode,
                latency_ms,
                1 if was_corrected else 0,
                retrieval_score,
                1 if cache_hit else 0,
                1 if error else 0,
            ),
        )
        conn.commit()
        conn.close()

        logger.info(
            "metric_recorded",
            query=query[:80],
            latency_ms=latency_ms,
            was_corrected=was_corrected,
            cache_hit=cache_hit,
            mode=mode,
            error=error,
        )

    def _get_latencies(self, cursor) -> List[float]:
        cursor.execute("SELECT latency_ms FROM query_metrics WHERE latency_ms IS NOT NULL")
        return [row[0] for row in cursor.fetchall()]

    def _get_mode_breakdown(self, cursor) -> Dict[str, dict]:
        cursor.execute(
            """
            SELECT mode,
                   COUNT(*) AS total,
                   SUM(was_corrected) AS corrections,
                   AVG(latency_ms) AS avg_latency,
                   AVG(retrieval_score) AS avg_retrieval
            FROM query_metrics
            GROUP BY mode
            """
        )
        breakdown = {}
        for row in cursor.fetchall():
            breakdown[row[0]] = {
                "total_queries": row[1],
                "total_corrections": row[2] or 0,
                "avg_latency_ms": row[3] or 0.0,
                "avg_retrieval_score": row[4] or 0.0,
            }
        return breakdown

    def get_metrics(self) -> Dict:
        """Aggregate metrics from persistent storage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM query_metrics")
        total_queries = cursor.fetchone()[0]

        if total_queries == 0:
            conn.close()
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
                "uptime_seconds": time.time() - self.start_time,
                "mode_breakdown": {},
            }

        cursor.execute("SELECT SUM(was_corrected) FROM query_metrics")
        total_corrections = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(error) FROM query_metrics")
        total_errors = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(cache_hit) FROM query_metrics")
        cache_hits = cursor.fetchone()[0] or 0
        cache_requests = total_queries

        cursor.execute("SELECT AVG(retrieval_score) FROM query_metrics")
        avg_retrieval = cursor.fetchone()[0] or 0.0

        latencies = self._get_latencies(cursor)

        mode_breakdown = self._get_mode_breakdown(cursor)
        conn.close()

        return {
            "total_queries": total_queries,
            "total_corrections": total_corrections,
            "correction_rate": total_corrections / total_queries if total_queries else 0.0,
            "avg_latency_ms": float(np.mean(latencies)) if latencies else 0.0,
            "p95_latency_ms": float(np.percentile(latencies, 95)) if latencies else 0.0,
            "p99_latency_ms": float(np.percentile(latencies, 99)) if latencies else 0.0,
            "error_rate": total_errors / total_queries if total_queries else 0.0,
            "cache_hit_rate": cache_hits / cache_requests if cache_requests else 0.0,
            "avg_retrieval_score": avg_retrieval,
            "uptime_seconds": time.time() - self.start_time,
            "mode_breakdown": mode_breakdown,
        }

    def reset(self):
        """Clear persisted metrics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM query_metrics")
        conn.commit()
        conn.close()
        self.start_time = time.time()
        logger.info("metrics_reset")


# Singleton instance
metrics_tracker = MetricsTracker()
