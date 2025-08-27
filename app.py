from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import requests
from io import BytesIO
import re

app = Flask(__name__)
CORS(app)

def extract_section_names(text):
    """Extract section names like 'Section: VARC' or 'Section: Quantitative Ability'"""
    pattern = r'Section:\s*([A-Za-z ]+)'
    return [s.strip() for s in re.findall(pattern, text)]

def extract_questions_from_text(text):
    """
    Extract questions where:
    - Question starts with Q. 1), Q. 2), etc.
    - Question text spans multiple lines until a) appears
    - Options a)-d) each on separate lines
    """
    question_pattern = r'Q\.\s*(\d+)\)\s*(.*?)\n(?=a\))'
    questions = []

    for match in re.finditer(question_pattern, text, re.DOTALL | re.MULTILINE):
        q_num = int(match.group(1))
        q_text = match.group(2).strip().replace('\n', ' ')

        # Extract options after question
        options_pattern = r'^([a-d])\)\s*(.*)'
        options_text = text[match.end():]
        options = []

        for line in options_text.splitlines():
            line = line.strip()
            m = re.match(options_pattern, line)
            if m:
                letter, opt_text = m.groups()
                options.append(f"{letter}) {opt_text.strip()}")
            # Stop when next question starts
            if re.match(r'^Q\.\s*\d+\)', line):
                break

        if q_text and len(options) >= 2:
            questions.append({
                "question_number": q_num,
                "question": q_text,
                "options": options
            })

    return questions

def extract_sections_with_questions(text):
    """
    Extract sections and their questions.
    """
    section_pattern = r'(Section:\s*[A-Za-z ]+)'
    sections = re.split(section_pattern, text)

    result = []
    it = iter(sections)
    first = next(it)  # may be text before first section

    for section_name in it:
        section_text = next(it, "")
        section_title = section_name.replace("Section:", "").strip()
        questions = extract_questions_from_text(section_text)
        result.append({
            "section": section_title,
            "questions": questions
        })

    return result

@app.route("/extract-sections", methods=["POST"])
def extract_sections():
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
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    full_text += f"=== PAGE {page_num + 1} ===\n" + text + "\n\n"

        sections = extract_section_names(full_text)
        
        return jsonify({
            "success": True,
            "total_sections": len(sections),
            "sections": sections,
            "debug_info": {
                "text_length": len(full_text),
                "first_500_chars": full_text[:500] if len(full_text) > 500 else full_text
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/extract-questions", methods=["POST"])
def extract_questions():
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
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    full_text += f"=== PAGE {page_num + 1} ===\n" + text + "\n\n"

        questions = extract_questions_from_text(full_text)

        return jsonify({
            "success": True,
            "total_questions": len(questions),
            "questions": questions,
            "debug_info": {
                "text_length": len(full_text),
                "first_500_chars": full_text[:500] if len(full_text) > 500 else full_text
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/extract-sections-questions", methods=["POST"])
def extract_sections_questions():
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
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    full_text += f"=== PAGE {page_num + 1} ===\n" + text + "\n\n"

        sections_with_questions = extract_sections_with_questions(full_text)

        return jsonify({
            "success": True,
            "total_sections": len(sections_with_questions),
            "sections": sections_with_questions
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=4000, debug=True)
