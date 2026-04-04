import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VIBETTER_CODEBASE_PATH = os.getenv("VIBETTER_CODEBASE_PATH", ".")
VIBETTER_ENV = os.getenv("VIBETTER_ENV", "development")
