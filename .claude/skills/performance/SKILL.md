---
name: performance
description: |
  Performance optimization, profiling, benchmarking, memory leaks, CPU usage,
  bundle size, load time, render performance, database queries, N+1 problems,
  caching strategies, lazy loading, code splitting, bottleneck identification.

  Trigger phrases: optimize performance, slow code, profile this, memory leak,
  high CPU, bundle too large, page load slow, render performance, N+1 query,
  database slow, cache this, lazy load, code split, bottleneck, benchmark,
  performance audit, speed up, too slow, optimize for speed, reduce memory,
  garbage collection, event loop blocking, async optimization.
---

# Performance

Tools for profiling and optimization.

## Primary Tools

### perf-profiler Agent
```bash
Task(subagent_type="perf-profiler", prompt="Find performance issues in <path>")
```
Static analysis for N+1 queries, expensive loops, memory leaks, bundle bloat.

### PAL Thinkdeep - Deep Analysis
```bash
mcp__pal__thinkdeep  # Complex performance investigation
```

## Frontend Performance

### Bundle Analysis
```bash
# Webpack
npx webpack-bundle-analyzer

# Vite
npx vite-bundle-visualizer

# Check bundle size
du -sh dist/
```

### Browser DevTools
```bash
mcp__chrome-devtools__performance_start_trace
mcp__chrome-devtools__performance_stop_trace
```

### Core Web Vitals
- LCP (Largest Contentful Paint) < 2.5s
- FID (First Input Delay) < 100ms
- CLS (Cumulative Layout Shift) < 0.1

## Backend Performance

### Python Profiling
```bash
python -m cProfile -s cumtime script.py
python -m memory_profiler script.py
```

### Database
```bash
# Explain query plans
EXPLAIN ANALYZE SELECT ...

# Find slow queries
grep -i "slow query" /var/log/mysql/
```

### N+1 Query Detection
```bash
# Look for queries in loops
grep -rn "for.*in.*:" --include="*.py" -A5 | grep -i "query\|select\|find"
```

## Optimization Patterns

### Caching
- Memoization for expensive computations
- Redis/Memcached for distributed cache
- HTTP caching headers

### Lazy Loading
- Dynamic imports for code splitting
- Intersection Observer for images
- Virtual scrolling for long lists

### Database
- Add indexes for frequent queries
- Batch operations instead of loops
- Use connection pooling
