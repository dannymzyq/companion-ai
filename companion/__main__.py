import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run("companion.server:app", host=settings.host, port=settings.port, log_level="info")
