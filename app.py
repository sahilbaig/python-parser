from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import requests
from io import BytesIO
import logging
from ollama import generate
import json
import re
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)

CHUNK_SIZE = 3000  # Adjust if needed

# ---------------------------
# Ollama Helpers
# ---------------------------
def parse_pdf_chunk_with_ollama(text_chunk: str):
    prompt = f"""
You are an expert at extracting exam directions from CAT exam PDFs.

ANALYZE THIS TEXT AND EXTRACT ONLY DIRECTION BLOCKS (ignore questions):

{text_chunk}

CRITICAL RULES:
1. Only extract blocks that start with "DIRECTIONS"
2. Identify the question range it applies to (e.g., "questions 1 to 5")
3. Return each direction block as a JSON object (not array) with this format:
{{
    "type": "description",
    "from": 1,
    "to": 5,
    "text": "..."
}}
4. Use ONLY text found in the PDF
5. Preserve original wording and formatting

IMPORTANT: Return ONLY JSON objects. Do NOT include explanations.
"""
    try:
        response = generate("llama2:latest", prompt)
        return response['response']
    except Exception as e:
        print(f"Ollama generation error: {e}")
        return ""

def parse_questions_with_ollama(chunk: str):
    prompt = f"""
TASK: Extract all numbered questions and their multiple choice options from the text below.
FORMAT: Return ONLY valid JSON array, no other text.

INSTRUCTIONS:
1. Find all questions that start with numbers like "1.", "2.", etc.
2. For each question, extract the question text (remove option numbers 1., 2., 3., 4.)
3. Map the options to a, b, c, d (1. → a, 2. → b, 3. → c, 4. → d)
4. Ignore any metadata, tables, or non-question content

REQUIRED JSON FORMAT:
[
  {{
    "number": 1,
    "text": "clean question text here",
    "options": {{
      "a": "option text from 1.",
      "b": "option text from 2.", 
      "c": "option text from 3.",
      "d": "option text from 4."
    }}
  }}
]

TEXT TO PROCESS:
{chunk}

IMPORTANT: Return ONLY JSON array.
"""
    try:
        response = generate("llama2:latest", prompt)
        return response['response']
    except Exception as e:
        print(f"Ollama generation error: {e}")
        return ""

# ---------------------------
# JSON Extraction
# ---------------------------
def extract_json_objects(raw_text):
    """Extract multiple JSON objects from Ollama output"""
    matches = re.findall(r'\{.*?\}', raw_text, re.DOTALL)
    valid_objects = []
    for obj_str in matches:
        try:
            obj = json.loads(obj_str)
            if isinstance(obj, dict) and "type" in obj and "from" in obj and "to" in obj and "text" in obj:
                valid_objects.append(obj)
        except json.JSONDecodeError:
            continue
    return valid_objects

def extract_json_array(raw_text):
    """Extract JSON array for questions"""
    try:
        cleaned = re.sub(r'```json|```', '', raw_text).strip()
        array_match = re.search(r'\[\s*\{.*\}\s*\]', cleaned, re.DOTALL)
        if array_match:
            return json.loads(array_match.group())
        # fallback: individual question objects
        objects = re.findall(r'\{\s*.*?"number".*?"text".*?"options".*?\}', cleaned, re.DOTALL)
        questions = []
        for obj_str in objects:
            try:
                questions.append(json.loads(obj_str))
            except:
                continue
        return questions
    except Exception as e:
        print("JSON parse error:", e)
        return []

# ---------------------------
# PDF Helpers
# ---------------------------
def chunk_text(text, max_len=3500):
    for i in range(0, len(text), max_len):
        yield text[i:i + max_len]

# ---------------------------
# Flask Routes
# ---------------------------
@app.route("/directions-only", methods=["POST"])
def pdf_directions():
    try:
        data = request.get_json()
        url = data.get("url")
        if not url:
            return jsonify({"error": "PDF URL is required"}), 400

        # Download PDF
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pdf_file = BytesIO(response.content)

        # Extract text from first few pages
        full_text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages[:3]:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                if len(full_text) > CHUNK_SIZE:
                    break

        start_idx = full_text.find("DIRECTIONS")
        chunk = full_text[start_idx:start_idx + CHUNK_SIZE] if start_idx != -1 else full_text[:CHUNK_SIZE]
        print(f"Processing text chunk: {chunk[:200]}...")

        raw_output = parse_pdf_chunk_with_ollama(chunk)
        print("Ollama output:", raw_output[:500] + "..." if len(raw_output) > 500 else raw_output)

        parsed = extract_json_objects(raw_output)

        return jsonify({
            "success": True,
            "directions": parsed,
            "chunk_preview": chunk[:200] + "..." if len(chunk) > 200 else chunk
        }), 200

    except Exception as e:
        print("Error parsing PDF:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/questions-only", methods=["POST"])
def pdf_questions():
    try:
        data = request.get_json()
        url = data.get("url")
        if not url:
            return jsonify({"error": "PDF URL is required"}), 400

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pdf_file = BytesIO(response.content)

        full_text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages[:5]:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                if len(full_text) > 5000:
                    break

        start_idx = full_text.find("1.")
        if start_idx == -1:
            return jsonify({"error": "No questions found in PDF"}), 404

        chunk = full_text[start_idx:start_idx + 4000]
        print(f"Processing questions chunk: {chunk[:200]}...")

        raw_output = parse_questions_with_ollama(chunk)
        print("Ollama output:", raw_output[:500] + "..." if len(raw_output) > 500 else raw_output)

        parsed = extract_json_array(raw_output)

        return jsonify({
            "success": True,
            "questions": parsed,
            "chunk_preview": chunk[:200] + "..." if len(chunk) > 200 else chunk
        }), 200

    except Exception as e:
        print("Error parsing PDF questions:", e)
        return jsonify({"error": str(e)}), 500

# ---------------------------
# Run App
# ---------------------------
if __name__ == "__main__":
    app.run(port=4000, debug=True)
