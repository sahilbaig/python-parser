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

# Increased chunk size to capture more context
CHUNK_SIZE = 3000

def parse_pdf_chunk_with_ollama(text_chunk: str):
    prompt = f"""
You are an expert at extracting exam directions and question descriptions from CAT exam PDFs.

ANALYZE THIS TEXT AND EXTRACT ALL DIRECTION BLOCKS:

{text_chunk}

CRITICAL RULES:
1. Extract ONLY the actual direction/description text blocks that appear before question sets
2. For each block, identify the question range it applies to (e.g., "questions 1 to 5")
3. Return valid JSON array with exact structure
4. Use ONLY text found in the PDF - no placeholders
5. Preserve the original wording and formatting

REQUIRED JSON FORMAT:
[
  {{
    "type": "description",
    "from": 1,
    "to": 5,
    "text": "DIRECTIONS for questions 1 to 5: Each of the following questions has one or more blank spaces..."
  }}
]

If no directions are found, return empty array: []
"""
    try:
        response = generate("llama2:latest", prompt)
        return response['response']
    except Exception as e:
        print(f"Ollama generation error: {e}")
        return "[]"

def extract_and_validate_json(output: str):
    """More robust JSON extraction and validation"""
    # Clean the output
    cleaned = output.strip()
    
    # Remove any text before the first [ and after the last ]
    start_idx = cleaned.find('[')
    end_idx = cleaned.rfind(']')
    
    if start_idx == -1 or end_idx == -1:
        return []
    
    json_str = cleaned[start_idx:end_idx+1]
    
    try:
        # Try to parse the JSON directly first
        parsed = json.loads(json_str)
        
        # Validate structure
        if isinstance(parsed, list):
            validated_items = []
            for item in parsed:
                # Check if item has required fields with correct types
                if (isinstance(item, dict) and 
                    'type' in item and 
                    'from' in item and 
                    'to' in item and 
                    'text' in item and
                    isinstance(item['from'], int) and
                    isinstance(item['to'], int)):
                    validated_items.append(item)
            return validated_items
        return []
    except json.JSONDecodeError:
        # Try to fix common JSON issues
        try:
            # Remove trailing commas
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            # Fix unquoted keys
            json_str = re.sub(r'(\s*)(\w+)(\s*):', r'\1"\2"\3:', json_str)
            parsed = json.loads(json_str)
            return parsed if isinstance(parsed, list) else []
        except:
            return []

@app.route("/all-questions", methods=["POST"])
def pdf_text():
    try:
        data = request.get_json()
        url = data.get("url")
        if not url:
            return jsonify({"error": "PDF URL is required"}), 400

        # Download PDF
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pdf_file = BytesIO(response.content)

        # Extract text from first few pages (where directions usually are)
        full_text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for i, page in enumerate(pdf.pages[:3]):  # First 3 pages
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
                if len(full_text) > CHUNK_SIZE:
                    break

        chunk = full_text[:CHUNK_SIZE]
        print(f"Processing text chunk: {chunk[:200]}...")

        # Send to Ollama
        raw_output = parse_pdf_chunk_with_ollama(chunk)
        print("Ollama output:", raw_output[:500] + "..." if len(raw_output) > 500 else raw_output)

        # Extract and validate JSON
        parsed_data = extract_and_validate_json(raw_output)
        
        return jsonify({
            "success": True,
            "descriptions": parsed_data,
            "chunk_preview": chunk[:200] + "..." if len(chunk) > 200 else chunk
        }), 200

    except Exception as e:
        print("Error parsing PDF:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=4000, debug=True)