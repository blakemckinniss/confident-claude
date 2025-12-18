---
name: error-handling
description: |
  Error handling patterns, exception handling, error boundaries, try-catch,
  error propagation, custom errors, error recovery, graceful degradation,
  error logging, error monitoring, stack traces, error types.

  Trigger phrases: error handling, exception, try catch, error boundary,
  handle error, custom error, error propagation, graceful degradation,
  error recovery, error logging, stack trace, unhandled exception,
  error type, throw error, catch error, finally block.
---

# Error Handling

Patterns for robust error handling.

## Primary Tools

### error-tracer Agent
```bash
Task(subagent_type="error-tracer", prompt="Trace error propagation in <path>")
```
Traces error paths, finds unhandled exceptions, maps error boundaries.

### PAL Debug
```bash
mcp__pal__debug  # Deep error investigation
```

## JavaScript/TypeScript

### Try-Catch
```typescript
try {
  await riskyOperation();
} catch (error) {
  if (error instanceof NetworkError) {
    // Handle network issues
  } else if (error instanceof ValidationError) {
    // Handle validation
  } else {
    throw error; // Re-throw unknown errors
  }
}
```

### Custom Errors
```typescript
class AppError extends Error {
  constructor(
    message: string,
    public code: string,
    public statusCode: number = 500
  ) {
    super(message);
    this.name = 'AppError';
  }
}

throw new AppError('User not found', 'USER_NOT_FOUND', 404);
```

### React Error Boundaries
```tsx
class ErrorBoundary extends React.Component {
  state = { hasError: false };

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    logError(error, info);
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback />;
    }
    return this.props.children;
  }
}
```

## Python

### Exception Handling
```python
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Validation failed: {e}")
    raise
except IOError as e:
    logger.error(f"IO error: {e}")
    return fallback_value
finally:
    cleanup()
```

### Custom Exceptions
```python
class AppError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code

raise AppError("Not found", "NOT_FOUND")
```

## Best Practices

### DO
- Catch specific error types
- Log errors with context
- Fail fast in development
- Provide useful error messages
- Use error boundaries in React

### DON'T
- Catch and ignore (except: pass)
- Catch Exception broadly
- Hide errors from users inappropriately
- Lose stack trace information
- Use errors for control flow

## Error Propagation

```typescript
// Let errors bubble up
async function getUser(id: string) {
  const user = await db.findUser(id);
  if (!user) throw new NotFoundError('User not found');
  return user;
}

// Catch at boundary
app.get('/users/:id', async (req, res) => {
  try {
    const user = await getUser(req.params.id);
    res.json(user);
  } catch (error) {
    if (error instanceof NotFoundError) {
      res.status(404).json({ error: error.message });
    } else {
      res.status(500).json({ error: 'Internal error' });
    }
  }
});
```

## Graceful Degradation

```typescript
async function getDataWithFallback() {
  try {
    return await fetchFromAPI();
  } catch {
    return getCachedData() ?? getDefaultData();
  }
}
```
