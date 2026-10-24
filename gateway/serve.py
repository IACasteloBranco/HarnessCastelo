import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Avoid Uvicorn's Proactor loop factory, which async psycopg does not support.
uvicorn.run("gateway.main:app", host="127.0.0.1", port=18080, loop="none")
