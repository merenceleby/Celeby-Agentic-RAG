import sqlite3
import structlog
from datetime import datetime
from typing import List, Dict
import os

logger = structlog.get_logger()

class FeedbackService:
    """Store and manage user feedback on answers"""
    
    def __init__(self, db_path: str = "/app/feedback.db"):
        self.db_path = db_path
        self._init_db()
        logger.info("feedback_service_init", db_path=db_path)
    
    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT,
                feedback INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                correction_attempts INTEGER DEFAULT 0,
                response_time_ms FLOAT,
                metadata TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        
        logger.info("feedback_db_initialized")
    
    def add_feedback(self, 
                     query: str, 
                     answer: str, 
                     feedback: int,
                     sources: List[str] = None,
                     correction_attempts: int = 0,
                     response_time_ms: float = 0,
                     metadata: Dict = None) -> int:
        """
        Add user feedback
        
        Args:
            query: User question
            answer: System answer
            feedback: 1 for like, 0 for dislike
            sources: List of source documents
            correction_attempts: Number of self-corrections
            response_time_ms: Response time
            metadata: Additional metadata
            
        Returns:
            Feedback ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        sources_str = "\n---\n".join(sources) if sources else ""
        metadata_str = str(metadata) if metadata else ""
        
        cursor.execute("""
            INSERT INTO feedback 
            (query, answer, sources, feedback, correction_attempts, response_time_ms, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (query, answer, sources_str, feedback, correction_attempts, response_time_ms, metadata_str))
        
        feedback_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info("feedback_added",
                   feedback_id=feedback_id,
                   query=query[:50],
                   feedback="like" if feedback == 1 else "dislike")
        
        return feedback_id
    
    def get_all_feedback(self, limit: int = 100) -> List[Dict]:
        """Get all feedback entries"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM feedback 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_feedback_stats(self) -> Dict:
        """Get feedback statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM feedback")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM feedback WHERE feedback = 1")
        likes = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM feedback WHERE feedback = 0")
        dislikes = cursor.fetchone()[0]
        
        cursor.execute("SELECT AVG(response_time_ms) FROM feedback")
        avg_response_time = cursor.fetchone()[0] or 0
        
        conn.close()
        
        satisfaction_rate = (likes / total * 100) if total > 0 else 0
        
        return {
            "total_feedback": total,
            "likes": likes,
            "dislikes": dislikes,
            "satisfaction_rate": satisfaction_rate,
            "avg_response_time_ms": avg_response_time
        }
    
    def get_negative_feedback(self, limit: int = 20) -> List[Dict]:
        """Get recent negative feedback for review"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM feedback 
            WHERE feedback = 0
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

# Singleton instance
feedback_service = FeedbackService()