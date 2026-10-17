import os
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")