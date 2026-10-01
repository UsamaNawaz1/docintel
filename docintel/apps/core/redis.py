"""Redis access.

Production uses redis-py. Local and tests use an in-process stand-in so
pubsub, digest locks, and readiness do not require a server. The stand-in is
not a Redis emulator; it only implements the calls this codebase makes.
"""

from __future__ import annotations

from typing import Protocol

from django.conf import settings


class RedisClient(Protocol):
    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None: ...

    def publish(self, channel: str, message: str) -> int: ...

    def ping(self) -> bool: ...


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        del ex
        if nx and name in self.values:
            return None
        self.values[name] = value
        return True

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    def ping(self) -> bool:
        return True


_memory = InMemoryRedis()


def get_redis() -> RedisClient:
    if settings.REDIS_BACKEND == "memory":
        return _memory
    import redis

    return redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )


def ping_redis(url: str) -> None:
    if settings.REDIS_BACKEND == "memory":
        _memory.ping()
        return
    import redis

    client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    client.ping()


def memory_redis() -> InMemoryRedis:
    return _memory
