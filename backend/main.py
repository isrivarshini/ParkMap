from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from backend.database import init_db
from backend.routes import router
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    # on startup: create tables if they don't exist
    await init_db()
    yield


app = FastAPI(
    title="ParkSpot API",
    description="Free, paid, and time-limited parking spots for Mountain View",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# serve static frontend files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ParkSpot API is running", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok"}