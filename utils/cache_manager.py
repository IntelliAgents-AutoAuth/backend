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
        if os.path.exists(self.cache_dir):
            for f in os.listdir(self.cache_dir):
                try:
                    os.remove(os.path.join(self.cache_dir, f))
                except Exception:
                    pass

    # ─────────────────────────────────────────
    # CASE-SPECIFIC HELPERS (Namespacing)
    # ─────────────────────────────────────────

    def get_by_case(self, case_id: str, key: str, ttl: Optional[int] = None) -> Optional[Any]:
        """Namespaced get for a specific case."""
        return self.get(f"{case_id}:{key}", ttl=ttl)

    def set_by_case(self, case_id: str, key: str, data: Any):
        """Namespaced set for a specific case."""
        self.set(f"{case_id}:{key}", data)

    def delete_by_case(self, case_id: str, key: str):
        """Namespaced delete for a specific case."""
        self.delete(f"{case_id}:{key}")

# Singleton instances for common needs
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
pdf_cache = CacheManager(os.path.join(backend_dir, ".cache", "pdf_texts"))
policy_cache = CacheManager(os.path.join(backend_dir, ".cache", "policies"))
general_cache = CacheManager(os.path.join(backend_dir, ".cache", "general"))

class PolicyRulesCache:
    """
    Specialized cache for the consolidated extracted_policy_rules.json file.
    This file stores structured rules for all ingested policies.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def load(self) -> list[dict]:
        """Load all rules from the JSON file."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load policy rules from {self.file_path}: {e}")
        return []

    def save(self, rules: list[dict]):
        """Save all rules to the JSON file."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(rules, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save policy rules to {self.file_path}: {e}")

    def update_rule(self, filename: str, result: dict):
        """Update or add a single rule entry by filename."""
        rules = self.load()
        existing_index = -1
        for i, r in enumerate(rules):
            if r.get("file") == filename:
                existing_index = i
                break
        
        if existing_index >= 0:
            rules[existing_index] = result
        else:
            rules.append(result)
        
        self.save(rules)

rules_cache = PolicyRulesCache(os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json"))
