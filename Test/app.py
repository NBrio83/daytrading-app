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
DATABASE_URL     = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://")


def init_db():
    if not DATABASE_URL:
        return
    import psycopg2
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id SERIAL PRIMARY KEY,
                    data JSONB NOT NULL,
                    saved_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

init_db()


def load_analyses():
    if DATABASE_URL:
        try:
            import psycopg2, psycopg2.extras
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT data FROM analyses ORDER BY saved_at DESC LIMIT 3")
                    return [row["data"] for row in cur.fetchall()]
        except Exception:
            return []
    try:
        with open(ANALYSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_analysis(entry):
    if DATABASE_URL:
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO analyses (data) VALUES (%s)", (json.dumps(entry),))
                cur.execute("""
                    DELETE FROM analyses WHERE id NOT IN (
                        SELECT id FROM analyses ORDER BY saved_at DESC LIMIT %s
                    )
                """, (MAX_SAVED,))
    else:
        analyses = load_analyses()
        analyses.insert(0, entry)
        os.makedirs(os.path.dirname(ANALYSES_FILE), exist_ok=True)
        with open(ANALYSES_FILE, "w", encoding="utf-8") as f:
            json.dump(analyses[:MAX_SAVED], f, ensure_ascii=False)


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
    save_analysis(body)
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
