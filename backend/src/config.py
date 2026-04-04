import os
from pathlib import Path
from dotenv import load_dotenv

# Always resolve .env relative to this file (backend/src/ -> backend/.env)
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Default to the working directory at server startup (i.e. the user's open project)
VIBETTER_CODEBASE_PATH = os.getenv("VIBETTER_CODEBASE_PATH") or os.getcwd()
VIBETTER_ENV = os.getenv("VIBETTER_ENV", "development")
