---
name: fastapi
description: |
  FastAPI framework, Pydantic models, dependency injection, background tasks,
  middleware, WebSockets, OAuth2, JWT, CORS, OpenAPI, async endpoints,
  path parameters, query parameters, request body, response models.

  Trigger phrases: fastapi, pydantic, dependency injection, background task,
  fastapi middleware, websocket, oauth2, jwt auth, cors, openapi, swagger,
  path parameter, query parameter, request body, response model, fastapi route,
  async endpoint, HTTPException.
---

# FastAPI

FastAPI patterns and best practices.

## Basic Setup

```python
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel

app = FastAPI(title="My API", version="1.0.0")

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = False

@app.get("/")
async def root():
    return {"message": "Hello World"}
```

## Path & Query Parameters

```python
@app.get("/items/{item_id}")
async def get_item(
    item_id: int,                          # Path parameter
    q: str | None = None,                  # Query parameter (optional)
    skip: int = 0,                         # Query with default
    limit: int = Query(default=10, le=100) # Validated query
):
    return {"item_id": item_id, "q": q}
```

## Request Body & Response

```python
class CreateUser(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True  # For ORM models

@app.post("/users", response_model=UserResponse, status_code=201)
async def create_user(user: CreateUser):
    db_user = await db.create_user(user)
    return db_user
```

## Dependency Injection

```python
async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    user = await verify_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

@app.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return user
```

## Authentication

```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.post("/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate(form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"sub": user.id}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}
```

## Background Tasks

```python
from fastapi import BackgroundTasks

def send_email(email: str, message: str):
    # Slow operation
    ...

@app.post("/notify")
async def notify(
    email: str,
    background_tasks: BackgroundTasks
):
    background_tasks.add_task(send_email, email, "Welcome!")
    return {"message": "Notification queued"}
```

## Middleware

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.perf_counter() - start)
    return response
```

## WebSockets

```python
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        print(f"Client {client_id} disconnected")
```

## Error Handling

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}}
    )

raise AppError("NOT_FOUND", "User not found", 404)
```

## Router Organization

```python
# routers/users.py
from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
async def list_users():
    ...

# main.py
from routers import users
app.include_router(users.router)
```
