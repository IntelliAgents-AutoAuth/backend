import os
import json
import hashlib
import time
import logging
from typing import Any, Optional, Dict, Callable

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Centralized caching utility for IntelliAgents.
    Supports file-based persistent caching and in-memory TTL caching.
    """
    
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._memory_cache: Dict[str, tuple[Any, float]] = {}

    def _get_cache_path(self, key: str) -> str:
        # Use MD5 hash for filename robustness
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{safe_key}.json")

    def get(self, key: str, ttl: Optional[int] = None) -> Optional[Any]:
        """
        Retrieve data from cache (RAM then Disk).
        
        Args:
            key: Cache key
            ttl: Time-to-live in seconds (optional)
            
        Returns:
            Cached data or None if missing/expired
        """
        now = time.time()
        
        # 1. Memory Check
        if key in self._memory_cache:
            data, timestamp = self._memory_cache[key]
            if ttl is None or (now - timestamp) < ttl:
                return data
            else:
                del self._memory_cache[key]

        # 2. Disk Check
        cache_path = self._get_cache_path(key)
        if os.path.exists(cache_path):
            try:
                # Check file modification time for TTL
                mtime = os.path.getmtime(cache_path)
                if ttl is None or (now - mtime) < ttl:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Backfill memory cache
                        self._memory_cache[key] = (data, mtime)
                        return data
                else:
                    # Expired disk cache
                    logger.info(f"Disk cache expired for key: {key}")
                    os.remove(cache_path) 
            except Exception as e:
                logger.warning(f"Failed to read disk cache for {key}: {e}")
        
        return None

    def set(self, key: str, data: Any):
        """Store data in cache (RAM and Disk)."""
        now = time.time()
        self._memory_cache[key] = (data, now)
        
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, default=str)
        except Exception as e:
            logger.warning(f"Failed to write disk cache for {key}: {e}")

    def delete(self, key: str):
        """Remove key from both RAM and Disk."""
        if key in self._memory_cache:
            del self._memory_cache[key]
        
        cache_path = self._get_cache_path(key)
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Failed to delete disk cache for {key}: {e}")

    def clear_all(self):
        """Clear all RAM and Disk cache."""
        self._memory_cache.clear()
        for f in os.listdir(self.cache_dir):
            try:
                os.remove(os.path.join(self.cache_dir, f))
            except Exception:
                pass

# Singleton instances for common needs
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
pdf_cache = CacheManager(os.path.join(backend_dir, ".cache", "pdf_texts"))
policy_cache = CacheManager(os.path.join(backend_dir, ".cache", "policies"))
general_cache = CacheManager(os.path.join(backend_dir, ".cache", "general"))
