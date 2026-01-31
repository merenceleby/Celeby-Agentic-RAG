import json
import os
import sqlite3
import structlog
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from config import settings

logger = structlog.get_logger()

class ChatHistoryService:
    """Manage chat conversations with history"""
    
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.CHAT_HISTORY_DB_PATH
        self._ensure_directory()
        self._init_db()
        logger.info("chat_history_service_init", db_path=self.db_path)

    def _ensure_directory(self):
        directory = os.path.dirname(self.db_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
    
    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_count INTEGER DEFAULT 0
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
        conn.close()
        
        logger.info("chat_history_db_initialized")
    
    def create_conversation(self, title: str = "New Chat") -> str:
        """Create a new conversation"""
        conversation_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO conversations (id, title)
            VALUES (?, ?)
        """, (conversation_id, title))
        
        conn.commit()
        conn.close()
        
        logger.info("conversation_created", id=conversation_id, title=title)
        
        return conversation_id
    
    def add_message(
        self, 
        conversation_id: str, 
        role: str, 
        content: str,
        metadata: Dict = None
    ) -> str:
        """Add a message to a conversation"""
        message_id = str(uuid.uuid4())
        metadata_str = json.dumps(metadata) if metadata else None
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert message
        cursor.execute("""
            INSERT INTO messages (id, conversation_id, role, content, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (message_id, conversation_id, role, content, metadata_str))
        
        # Update conversation
        cursor.execute("""
            UPDATE conversations 
            SET updated_at = CURRENT_TIMESTAMP,
                message_count = message_count + 1
            WHERE id = ?
        """, (conversation_id,))
        
        conn.commit()
        conn.close()
        
        logger.info("message_added", 
                   conversation_id=conversation_id,
                   role=role,
                   message_id=message_id)
        
        return message_id
    
    def get_conversation_history(self, conversation_id: str, limit: int = 50) -> List[Dict]:
        """Get all messages in a conversation"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            LIMIT ?
        """, (conversation_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            msg = {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"]
            }
            if row["metadata"]:
                msg["metadata"] = json.loads(row["metadata"])
            messages.append(msg)
        
        conn.close()
        
        return messages
    
    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Get a single conversation row"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM conversations WHERE id = ?
        """, (conversation_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_all_conversations(self, limit: int = 50) -> List[Dict]:
        """Get all conversations (for sidebar)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, title, created_at, updated_at, message_count
            FROM conversations
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))
        
        conversations = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return conversations
    
    def update_conversation_title(self, conversation_id: str, title: str):
        """Update conversation title"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE conversations 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (title, conversation_id))
        
        conn.commit()
        conn.close()
        
        logger.info("conversation_title_updated", id=conversation_id, title=title)
    
    def delete_conversation(self, conversation_id: str):
        """Delete a conversation and all its messages"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        
        conn.commit()
        conn.close()
        
        logger.info("conversation_deleted", id=conversation_id)
    
    def export_conversation(self, conversation_id: str) -> Dict:
        """Export conversation as JSON"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get conversation info
        cursor.execute("""
            SELECT * FROM conversations WHERE id = ?
        """, (conversation_id,))
        
        conversation = dict(cursor.fetchone())
        
        # Get messages
        cursor.execute("""
            SELECT * FROM messages WHERE conversation_id = ?
            ORDER BY created_at ASC
        """, (conversation_id,))
        
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            if msg.get("metadata"):
                msg["metadata"] = json.loads(msg["metadata"])
            messages.append(msg)
        
        conn.close()
        
        return {
            "conversation": conversation,
            "messages": messages,
            "exported_at": datetime.now().isoformat()
        }
    
    def import_conversation(self, data: Dict) -> str:
        """Import a conversation from JSON"""
        conversation_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create conversation
        conv = data["conversation"]
        cursor.execute("""
            INSERT INTO conversations (id, title, message_count)
            VALUES (?, ?, ?)
        """, (conversation_id, conv.get("title", "Imported Chat"), len(data["messages"])))
        
        # Import messages
        for msg in data["messages"]:
            message_id = str(uuid.uuid4())
            metadata_str = json.dumps(msg.get("metadata")) if msg.get("metadata") else None
            
            cursor.execute("""
                INSERT INTO messages (id, conversation_id, role, content, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (message_id, conversation_id, msg["role"], msg["content"], metadata_str))
        
        conn.commit()
        conn.close()
        
        logger.info("conversation_imported", id=conversation_id, messages=len(data["messages"]))
        
        return conversation_id

# Singleton instance
chat_history_service = ChatHistoryService()
