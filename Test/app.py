import os
import hmac
import json
import base64
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from dotenv import load_dotenv
from tools.analyze_chart import analyze_chart_image

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))

ALLOWED_TYPES    = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ANALYSES_FILE    = os.path.join(os.path.dirname(__file__), ".tmp", "saved_analyses.json")
MAX_SAVED        = 3


def load_analyses():
    try:
        with open(ANALYSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_analyses(analyses):
    os.makedirs(os.path.dirname(ANALYSES_FILE), exist_ok=True)
    with open(ANALYSES_FILE, "w", encoding="utf-8") as f:
        json.dump(analyses, f, ensure_ascii=False)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_users():
    users = {}
    for entry in os.environ.get("APP_USERS", "").split(","):
        entry = entry.strip()
        if ":" in entry:
            u, p = entry.split(":", 1)
            users[u.strip()] = p.strip()
    return users


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users    = get_users()
        stored   = users.get(username, "")
        if stored and hmac.compare_digest(password, stored):
            session["logged_in"] = True
            session["username"]  = username
            return redirect(url_for("index"))
        error = "Fel användarnamn eller lösenord."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/analyses", methods=["GET"])
@login_required
def get_analyses():
    return jsonify(load_analyses())


@app.route("/analyses", methods=["POST"])
@login_required
def post_analysis():
    body = request.get_json(silent=True) or {}
    analyses = load_analyses()
    analyses.insert(0, body)
    analyses = analyses[:MAX_SAVED]
    save_analyses(analyses)
    return jsonify({"ok": True})


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    if "images" not in request.files:
        return jsonify({"error": "Inga bilder uppladdades"}), 400

    files = request.files.getlist("images")
    image_data_list = []

    for f in files:
        if not f.filename:
            continue
        media_type = f.content_type or "image/jpeg"
        if media_type not in ALLOWED_TYPES:
            return jsonify({"error": f"Filformat stöds ej: {media_type}. Använd JPEG, PNG eller WebP."}), 400
        raw = f.read()
        b64 = base64.standard_b64encode(raw).decode("utf-8")
        image_data_list.append({"data": b64, "media_type": media_type})

    if not image_data_list:
        return jsonify({"error": "Inga giltiga bilder hittades"}), 400

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY saknas i .env-filen"}), 500

    try:
        result = analyze_chart_image(image_data_list)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
