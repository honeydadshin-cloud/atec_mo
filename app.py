import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from gtts import gTTS

_BASE_DIR = Path(__file__).resolve().parent
_ENV_PATHS = (_BASE_DIR / ".env", _BASE_DIR.parent / ".env")

GEMINI_MODEL = "gemini-2.5-flash"


def get_gemini_api_key() -> str:
    for env_path in _ENV_PATHS:
        load_dotenv(env_path, override=True)
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

LANGUAGES = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh-CN": "中文(简体)",
    "zh-TW": "中文(繁體)",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "vi": "Tiêng Việt",
    "th": "ไทย",
    "ru": "Русский",
    "pt": "Português",
    "ar": "العربية",
    "id": "Bahasa Indonesia",
}

CHUNK_SIZE = 4500


def split_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks = []
    current = ""
    paragraphs = re.split(r"(\n\s*\n)", text)

    for part in paragraphs:
        if len(current) + len(part) <= CHUNK_SIZE:
            current += part
        else:
            if current:
                chunks.append(current)
            if len(part) <= CHUNK_SIZE:
                current = part
            else:
                sentences = re.split(r"(?<=[.!?。！？\n])\s*", part)
                current = ""
                for sentence in sentences:
                    if len(current) + len(sentence) <= CHUNK_SIZE:
                        current += sentence
                    else:
                        if current:
                            chunks.append(current)
                        while len(sentence) > CHUNK_SIZE:
                            chunks.append(sentence[:CHUNK_SIZE])
                            sentence = sentence[CHUNK_SIZE:]
                        current = sentence
    if current:
        chunks.append(current)
    return chunks


def translate_text(text: str, source: str, target: str) -> str:
    if source == target:
        return text

    translator = GoogleTranslator(source=source, target=target)
    chunks = split_text(text)
    translated = [translator.translate(chunk) for chunk in chunks]
    return "".join(translated)


def read_txt(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_docx(raw: bytes) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []

    with zipfile.ZipFile(io.BytesIO(raw)) as docx:
        xml = docx.read("word/document.xml")
    root = ElementTree.fromstring(xml)

    for p in root.findall(".//w:p", ns):
        parts = [node.text for node in p.findall(".//w:t", ns) if node.text]
        if parts:
            paragraphs.append("".join(parts))

    return "\n\n".join(paragraphs)


def summarize_to_three_lines(text: str) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY가 설정되지 않았습니다. "
            "c:\\ai 교육\\.env 파일에 키를 저장했는지 확인해 주세요."
        )

    prompt = (
        "아래 한국어 문서를 핵심만 담아 정확히 3줄로 요약하세요.\n"
        "규칙:\n"
        "- 반드시 3줄만 출력\n"
        "- 각 줄은 한 문장\n"
        "- 번호, 불릿, 제목 없이 줄바꿈만 사용\n"
        "- 한국어로 작성\n\n"
        f"문서:\n{text[:12000]}"
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini API 오류 ({exc.code}): {body[:200]}") from exc

    try:
        summary = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini 응답을 해석하지 못했습니다.") from exc

    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    lines = [re.sub(r"^[\d]+[\.\)]\s*|^[-•*]\s*", "", line) for line in lines]
    lines = [line for line in lines if line]

    if len(lines) > 3:
        lines = lines[:3]
    while len(lines) < 3 and summary:
        lines.append("")

    return "\n".join(lines[:3])


def text_to_speech_audio(text: str) -> bytes:
    buffer = io.BytesIO()
    gTTS(text=text, lang="ko").write_to_fp(buffer)
    buffer.seek(0)
    return buffer.read()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    source = data.get("source") or "auto"
    target = data.get("target") or "en"

    if not text:
        return jsonify({"error": "번역할 텍스트를 입력해 주세요."}), 400
    if target not in LANGUAGES:
        return jsonify({"error": "지원하지 않는 대상 언어입니다."}), 400
    if source != "auto" and source not in LANGUAGES:
        return jsonify({"error": "지원하지 않는 원본 언어입니다."}), 400

    try:
        result = translate_text(text, source, target)
        return jsonify({"result": result, "chars": len(text)})
    except Exception as exc:
        return jsonify({"error": f"번역 중 오류가 발생했습니다: {exc}"}), 500


@app.route("/api/translate-file", methods=["POST"])
def api_translate_file():
    uploaded = request.files.get("file")
    source = request.form.get("source") or "auto"
    target = request.form.get("target") or "ko"

    if not uploaded or not uploaded.filename:
        return jsonify({"error": "파일을 선택해 주세요."}), 400
    if target not in LANGUAGES:
        return jsonify({"error": "지원하지 않는 대상 언어입니다."}), 400

    filename = uploaded.filename
    ext = os.path.splitext(filename)[1].lower()
    raw = uploaded.read()

    try:
        if ext == ".txt":
            text = read_txt(raw)
        elif ext == ".docx":
            text = read_docx(raw)
        else:
            return jsonify({"error": "지원 형식: .txt, .docx"}), 400

        if not text.strip():
            return jsonify({"error": "문서에서 텍스트를 찾을 수 없습니다."}), 400

        result = translate_text(text, source, target)
        base = os.path.splitext(filename)[0]
        out_name = f"{base}_{target}.txt"

        return jsonify({
            "result": result,
            "filename": out_name,
            "original_chars": len(text),
        })
    except Exception as exc:
        return jsonify({"error": f"파일 처리 중 오류: {exc}"}), 500


@app.route("/api/summarize", methods=["POST"])
def api_summarize():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "요약할 텍스트가 없습니다."}), 400

    try:
        summary = summarize_to_three_lines(text)
        lines = [line for line in summary.splitlines() if line.strip()]
        return jsonify({"summary": summary, "lines": lines})
    except Exception as exc:
        return jsonify({"error": f"요약 중 오류: {exc}"}), 500


@app.route("/api/tts", methods=["POST"])
def api_tts():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "읽을 텍스트가 없습니다."}), 400

    try:
        audio = text_to_speech_audio(text)
        return send_file(
            io.BytesIO(audio),
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="summary.mp3",
        )
    except Exception as exc:
        return jsonify({"error": f"TTS 생성 오류: {exc}"}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(silent=True) or {}
    content = data.get("content") or ""
    filename = data.get("filename") or "translated.txt"

    if not content.strip():
        return jsonify({"error": "다운로드할 내용이 없습니다."}), 400

    buffer = io.BytesIO(content.encode("utf-8-sig"))
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="text/plain; charset=utf-8",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
