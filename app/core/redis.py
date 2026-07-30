import redis
from app.core.config import settings

_redis_pool = None

def get_redis_client() -> redis.Redis:
    """
    Returns a thread-safe, connection-pooled Redis client instance.
    Prevents connection leaks by reusing a shared ConnectionPool across tasks.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL_FORMATTED,
            max_connections=10,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            decode_responses=True
        )
    return redis.Redis(connection_pool=_redis_pool)
