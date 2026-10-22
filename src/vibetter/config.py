import os
from pathlib import Path
from dotenv import load_dotenv

# Settings live in ~/.vibetter/.env (written by the installer).
load_dotenv(dotenv_path=Path.home() / ".vibetter" / ".env")

# Default to the working directory at server startup (i.e. the user's open project)
VIBETTER_CODEBASE_PATH = os.getenv("VIBETTER_CODEBASE_PATH") or os.getcwd()
VIBETTER_ENV = os.getenv("VIBETTER_ENV", "development")
