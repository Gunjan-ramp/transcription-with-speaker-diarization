from openai import OpenAI
import httpx
from app.core.config import settings

timeout = httpx.Timeout(
    connect=120.0,
    read=1800.0,
    write=600.0,
    pool=60.0
)

# OpenAI client
client = OpenAI(
    api_key=settings.openai_api_key,
    timeout=timeout
)
