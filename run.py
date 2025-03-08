import asyncio
from hypercorn.config import Config
from hypercorn.asyncio import serve
from app import asgi_app

async def main():
    config = Config()
    config.bind = ["localhost:5000"]
    config.use_reloader = True
    await serve(asgi_app, config)

if __name__ == "__main__":
    asyncio.run(main()) 