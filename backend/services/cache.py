import redis
import json
import hashlib
from config import settings
import structlog
from typing import Optional, Any

logger = structlog.get_logger()

class CacheService:
    """Redis-based caching service"""
    
    def __init__(self):
        try:
            self.client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True
            )
            self.client.ping()
            logger.info("cache_service_init", status="connected")
        except Exception as e:
            logger.warning("cache_service_init", status="failed", error=str(e))
            self.client = None
    
    def _generate_key(self, prefix: str, value: str) -> str:
        """Generate cache key with hash"""
        hash_value = hashlib.md5(value.encode()).hexdigest()
        return f"{prefix}:{hash_value}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.client:
            return None
        
        try:
            value = self.client.get(key)
            if value:
                logger.info("cache_hit", key=key)
                return json.loads(value)
            logger.info("cache_miss", key=key)
            return None
        except Exception as e:
            logger.error("cache_get_error", key=key, error=str(e))
            return None
    
    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache with TTL"""
        if not self.client:
            return False
        
        try:
            if ttl is None:
                ttl = settings.REDIS_TTL
            
            self.client.setex(
                key,
                ttl,
                json.dumps(value)
            )
            logger.info("cache_set", key=key, ttl=ttl)
            return True
        except Exception as e:
            logger.error("cache_set_error", key=key, error=str(e))
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.client:
            return False
        
        try:
            self.client.delete(key)
            logger.info("cache_delete", key=key)
            return True
        except Exception as e:
            logger.error("cache_delete_error", key=key, error=str(e))
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern"""
        if not self.client:
            return 0
        
        try:
            keys = self.client.keys(pattern)
            if keys:
                deleted = self.client.delete(*keys)
                logger.info("cache_clear_pattern", pattern=pattern, deleted=deleted)
                return deleted
            return 0
        except Exception as e:
            logger.error("cache_clear_error", pattern=pattern, error=str(e))
            return 0

# Singleton instance
cache_service = CacheService()