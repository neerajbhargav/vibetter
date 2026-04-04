import os
import time
import json
import asyncio
from gtts import gTTS
from typing import Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google import genai
from google.genai import types as genai_types
import sys
import os.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEMINI_API_KEY, VIBETTER_CODEBASE_PATH

# Configure Gemini Native SDK (google-genai)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODEL_IDENTIFIER = os.getenv("VIBETTER_MODEL", "gemini-2.0-flash")

class MasterContextManager(FileSystemEventHandler):
    def __init__(self, codebase_path: str):
        self.codebase_path = codebase_path
        self.master_context = ""
        self.build_context()
        
        # Engineering Decision: Watchdog Observer for Auto-Sync
        # As requested, this ensures the Master Context is instantly updated in memory
        # when you save a file, preventing stale reasoning without manual regeneration.
        self.observer = Observer()
        self.observer.schedule(self, str(os.path.abspath(codebase_path)), recursive=True)
        self.observer.start()

    def build_context(self):
        """Recursively parses text-based code files into one massive context payload."""
        context_parts = []
        for root, dirs, files in os.walk(self.codebase_path):
            # Exclude massive static/binary folders
            dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', '__pycache__', 'dist', '.venv', 'venv')]
            for file in files:
                if file.endswith(('.py', '.js', '.vue', '.ts', '.md', '.json', '.html', '.css', '.env.example')):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                            context_parts.append(f"--- FILE: {filepath} ---\n{content}\n")
                    except Exception:
                        pass
        self.master_context = "\n".join(context_parts)
    def on_modified(self, event):
        # Trigger contextual rebuild on file save
        if not event.is_directory and not event.src_path.endswith('.tmp'):
            self.build_context()

# Initialize singleton context manager
context_manager = MasterContextManager(VIBETTER_CODEBASE_PATH)

async def ask_gemini_with_context(question: str, target_file: str = None) -> str:
    """Uses Gemini to explain code with mandatory file:line source-grounding."""
    prompt = f"SYSTEM INSTRUCTION:\nYou are VIBETTER, an expert AI Infrastructure Architect. Use the following exact codebase Master Context as your sole reference for answering. Always provide exact file:line citations when explaining 'Why' or 'How' something works.\n\n"
    prompt += f"<master_context>\n{context_manager.master_context}\n</master_context>\n\n"
    if target_file:
        prompt += f"Target File to analyze: {target_file}\n"
    prompt += f"Question: {question}\n\nAnswer explicitly with grounded citations."
    
    response = await asyncio.to_thread(client.models.generate_content, model=MODEL_IDENTIFIER, contents=prompt)
    return response.text

async def generate_architecture_json() -> Dict[str, Any]:
    """Generates the structured Vue Flow graph from the Master Context"""
    prompt = f"Analyze the following codebase and generate a JSON object representing a dependency graph, tailored perfectly for `vue-flow`. It must contain 2 keys: 'nodes' and 'edges'. Ensure logical grouping and coordinate placements aren't totally overlapping.\n\nCodebase:\n{context_manager.master_context}"

    # Applying Structured Output requirement for standardizing the Vue map
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL_IDENTIFIER,
        contents=prompt,
        config=genai_types.GenerateContentConfig(response_mime_type="application/json")
    )
    try:
        return json.loads(response.text)
    except Exception as e:
        return {"error": "Failed to parse JSON architecture", "details": str(e), "nodes": [], "edges": []}

async def generate_audio_explanation(question: str, target_file: str = None) -> str:
    """Generates an audio explanation describing the code and saves it to an mp3 file."""
    transcript_prompt = f"SYSTEM INSTRUCTION: You are VIBETTER, an AI Architecture Podcast Host. Produce a short conversational transcript explaining the following question based on the Master Context. Make it engaging to listen to without complex formatting.\n\n<master_context>\n{context_manager.master_context}\n</master_context>\n\n"
    if target_file:
        transcript_prompt += f"Target File: {target_file}\n"
    transcript_prompt += f"Question: {question}\n\nAct as a human recording a podcast."

    try:
        response = await asyncio.to_thread(client.models.generate_content, model=MODEL_IDENTIFIER, contents=transcript_prompt)
        transcript_text = response.text
        
        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"explanation_{int(time.time())}.mp3")
        
        # Audio compilation
        tts = gTTS(text=transcript_text, lang='en', slow=False)
        tts.save(filepath)
        return f"Audio successfully generated and saved to: {os.path.abspath(filepath)}\n\nTranscript Snippet:\n{transcript_text[:300]}..."
    except Exception as e:
        return f"Error building audio file: {e}"
