---
name: api-development
description: |
  API design, REST endpoints, GraphQL, OpenAPI, request handling,
  response formatting, authentication, rate limiting, versioning,
  API documentation, error responses, middleware, routing.

  Trigger phrases: create API, REST endpoint, GraphQL schema, OpenAPI,
  API design, request handler, response format, API authentication,
  rate limit, API versioning, API docs, swagger, error response,
  middleware, route handler, HTTP method, status code, API testing.
---

# API Development

Tools for building and designing APIs.

## Primary Tools

### api-cartographer Agent
```bash
Task(subagent_type="api-cartographer", prompt="Map API endpoints in <path>")
```
Builds complete API map with endpoints, types, auth requirements.

### PAL API Lookup
```bash
mcp__pal__apilookup  # Current API/SDK documentation
```

## REST Design

### Resource Naming
```
GET    /users          # List
POST   /users          # Create
GET    /users/:id      # Read
PUT    /users/:id      # Update
DELETE /users/:id      # Delete
```

### HTTP Status Codes
| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Server Error |

### Response Format
```json
{
  "data": { ... },
  "meta": { "total": 100, "page": 1 },
  "error": null
}
```

## Express.js Patterns

```javascript
// Route handler
router.get('/users/:id', async (req, res) => {
  const user = await User.findById(req.params.id);
  if (!user) return res.status(404).json({ error: 'Not found' });
  res.json({ data: user });
});

// Middleware
const auth = (req, res, next) => {
  const token = req.headers.authorization;
  if (!valid(token)) return res.status(401).json({ error: 'Unauthorized' });
  next();
};
```

## FastAPI Patterns

```python
from fastapi import FastAPI, HTTPException

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")
    return {"data": user}
```

## OpenAPI / Swagger

```yaml
openapi: 3.0.0
paths:
  /users:
    get:
      summary: List users
      responses:
        '200':
          description: Success
```

## Authentication

### JWT
```javascript
const token = jwt.sign({ userId: user.id }, SECRET, { expiresIn: '1h' });
const decoded = jwt.verify(token, SECRET);
```

### API Keys
```javascript
const apiKey = req.headers['x-api-key'];
if (!validKeys.includes(apiKey)) return res.status(401).send();
```

## Rate Limiting

```javascript
import rateLimit from 'express-rate-limit';

const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100 // requests per window
});
```

## Testing APIs

```bash
# curl
curl -X POST http://localhost:3000/users -H "Content-Type: application/json" -d '{"name":"test"}'

# httpie
http POST :3000/users name=test
```
