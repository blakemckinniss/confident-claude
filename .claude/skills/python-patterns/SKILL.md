---
name: python-patterns
description: |
  Python patterns, decorators, context managers, generators, async/await,
  dataclasses, type hints, protocols, ABCs, metaclasses, descriptors,
  itertools, functools, pathlib, comprehensions, walrus operator.

  Trigger phrases: python decorator, context manager, generator, async python,
  dataclass, type hint, protocol, ABC, metaclass, descriptor, itertools,
  functools, pathlib, comprehension, walrus operator, python pattern,
  python best practice, dunder method, magic method.
---

# Python Patterns

Modern Python patterns and idioms.

## Decorators

### Basic Decorator
```python
from functools import wraps

def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        print(f"{func.__name__}: {time.perf_counter() - start:.4f}s")
        return result
    return wrapper

@timer
def slow_function():
    time.sleep(1)
```

### Decorator with Arguments
```python
def retry(max_attempts: int = 3, delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
        return wrapper
    return decorator

@retry(max_attempts=5)
def flaky_api_call():
    ...
```

## Context Managers

```python
from contextlib import contextmanager

@contextmanager
def timer_context(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        print(f"{name}: {time.perf_counter() - start:.4f}s")

with timer_context("operation"):
    do_work()

# Class-based
class DatabaseConnection:
    def __enter__(self):
        self.conn = connect()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False  # Don't suppress exceptions
```

## Generators

```python
# Generator function
def fibonacci(n: int):
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b

# Generator expression
squares = (x**2 for x in range(10))

# Send values to generator
def accumulator():
    total = 0
    while True:
        value = yield total
        total += value
```

## Async/Await

```python
import asyncio
import aiohttp

async def fetch(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def fetch_all(urls: list[str]) -> list[dict]:
    tasks = [fetch(url) for url in urls]
    return await asyncio.gather(*tasks)

# Run
asyncio.run(fetch_all(['url1', 'url2']))
```

## Dataclasses

```python
from dataclasses import dataclass, field

@dataclass
class User:
    name: str
    email: str
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        self.email = self.email.lower()

# Frozen (immutable)
@dataclass(frozen=True)
class Point:
    x: float
    y: float
```

## Type Hints

```python
from typing import TypeVar, Generic, Protocol, Callable

T = TypeVar('T')

# Generic class
class Stack(Generic[T]):
    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

# Protocol (structural typing)
class Comparable(Protocol):
    def __lt__(self, other: Any) -> bool: ...

def sort_items(items: list[Comparable]) -> list[Comparable]:
    return sorted(items)

# Callable
Handler = Callable[[str, int], bool]
```

## Useful Patterns

### Walrus Operator
```python
if (n := len(data)) > 10:
    print(f"Processing {n} items")

while (line := file.readline()):
    process(line)
```

### Comprehensions
```python
# Dict comprehension
{k: v for k, v in items if v > 0}

# Set comprehension
{x.lower() for x in words}

# Nested (flatten)
[item for sublist in nested for item in sublist]
```

### functools
```python
from functools import lru_cache, partial, reduce

@lru_cache(maxsize=128)
def expensive(n: int) -> int:
    return sum(range(n))

add_five = partial(add, 5)
```

### itertools
```python
from itertools import chain, groupby, islice, cycle

# Chain iterables
chain([1, 2], [3, 4])  # 1, 2, 3, 4

# Group by key
for key, group in groupby(sorted(items, key=lambda x: x.type), key=lambda x: x.type):
    print(key, list(group))
```
