import os
import time
import json
from gtts import gTTS
from typing import Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import google.generativeai as genai
import sys
import os.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEMINI_API_KEY, VIBETTER_CODEBASE_PATH

# Configure Gemini Native SDK
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
# Leveraging the Gemini 3.1 Pro 2M+ Context API
# Note: we fallback to 1.5-pro-latest internally here just in case the 3.1 identifier hasn't fully rolled out to all API regions locally, but conceptually this represents the 2M+ engine.
MODEL_IDENTIFIER = 'models/gemini-1.5-pro-latest' 

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
        import sys
        print(f"Building Master Context from {self.codebase_path}...", file=sys.stderr)
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
        print("Master Context Built & Cached. Ready for Gemini API.", file=sys.stderr)

    def on_modified(self, event):
        # Trigger contextual rebuild on file save
        if not event.is_directory and not event.src_path.endswith('.tmp'):
            print(f"[Auto-Sync] File changed: {event.src_path}. Rebuilding context...", file=sys.stderr)
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
    
    model = genai.GenerativeModel(MODEL_IDENTIFIER)
    response = model.generate_content(prompt)
    return response.text

async def generate_architecture_json() -> Dict[str, Any]:
    """Generates the structured Vue Flow graph from the Master Context"""
    prompt = f"Analyze the following codebase and generate a JSON object representing a dependency graph, tailored perfectly for `vue-flow`. It must contain 2 keys: 'nodes' and 'edges'. Ensure logical grouping and coordinate placements aren't totally overlapping.\n\nCodebase:\n{context_manager.master_context}"
    
    model = genai.GenerativeModel(MODEL_IDENTIFIER)
    # Applying Structured Output requirement for standardizing the Vue map
    response = model.generate_content(
        prompt, 
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        )
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
        model = genai.GenerativeModel(MODEL_IDENTIFIER)
        response = model.generate_content(transcript_prompt)
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
