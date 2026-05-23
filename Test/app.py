import os
import hmac
import json
import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
            cur.execute("""
                ALTER TABLE analyses ADD COLUMN IF NOT EXISTS panel VARCHAR(1) DEFAULT 'a'
            """)

init_db()


def load_analyses(panel):
    if DATABASE_URL:
        try:
            import psycopg2, psycopg2.extras
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT data FROM analyses WHERE panel = %s ORDER BY saved_at DESC LIMIT 3",
                        (panel,)
                    )
                    return [row["data"] for row in cur.fetchall()]
        except Exception:
            return []
    try:
        with open(ANALYSES_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, list):
            return stored if panel == "a" else []
        return stored.get(panel, [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_analysis(entry, panel):
    if DATABASE_URL:
        import psycopg2
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO analyses (data, panel) VALUES (%s, %s)",
                    (json.dumps(entry), panel)
                )
                cur.execute("""
                    DELETE FROM analyses WHERE panel = %s AND id NOT IN (
                        SELECT id FROM analyses WHERE panel = %s ORDER BY saved_at DESC LIMIT %s
                    )
                """, (panel, panel, MAX_SAVED))
    else:
        try:
            with open(ANALYSES_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, list):
                stored = {"a": stored, "b": []}
        except (FileNotFoundError, json.JSONDecodeError):
            stored = {"a": [], "b": []}
        panel_list = stored.get(panel, [])
        panel_list.insert(0, entry)
        stored[panel] = panel_list[:MAX_SAVED]
        os.makedirs(os.path.dirname(ANALYSES_FILE), exist_ok=True)
        with open(ANALYSES_FILE, "w", encoding="utf-8") as f:
            json.dump(stored, f, ensure_ascii=False)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/send-email") or request.path.startswith("/analyze"):
                return jsonify({"error": "Ej inloggad"}), 401
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
    panel = request.args.get("panel", "a")
    return jsonify(load_analyses(panel))


@app.route("/analyses", methods=["POST"])
@login_required
def post_analysis():
    body  = request.get_json(silent=True) or {}
    panel = body.pop("panel", "a")
    save_analysis(body, panel)
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

    panel = request.form.get("panel", "a")

    try:
        result = analyze_chart_image(image_data_list, panel)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _fmt(n):
    if n is None:
        return "—"
    num = float(n)
    s = f"{num:,.2f}" if num % 1 != 0 else f"{num:,.0f}"
    return s.replace(",", " ")


def _scenario_html(sc, label, color):
    entry_mid = (sc.get("entry_low", 0) + sc.get("entry_high", 0)) / 2
    targets = [(k, sc[k], sc.get(f"rr_{k}", "")) for k in ("t1", "t2", "t3") if sc.get(k) is not None]
    rows = "".join(
        f"<tr><td>T{k[1].upper()}</td><td>{_fmt(p)}</td><td style='color:{color}'>{rr}</td></tr>"
        for k, p, rr in targets
    )
    return f"""
    <table width="100%" cellpadding="6" style="border-collapse:collapse;margin-bottom:16px">
      <tr><td colspan="3" style="background:{color};color:#fff;font-weight:700;padding:8px 10px;border-radius:4px 4px 0 0">
        {label}
      </td></tr>
      <tr style="background:#1e2433"><td>Entry</td><td>{_fmt(sc.get("entry_low"))} – {_fmt(sc.get("entry_high"))}</td><td></td></tr>
      <tr style="background:#181c2a"><td>Stop Loss</td><td style="color:#e53935">{_fmt(sc.get("stop_loss"))}</td><td></td></tr>
      {rows}
      <tr style="background:#1e2433"><td colspan="3" style="font-size:13px;color:#aab">{sc.get("description","")}</td></tr>
    </table>"""


def _build_email_html(data):
    short_html = _scenario_html(data.get("short_scenario", {}), "SHORT – Primär trade", "#e53935")
    long_html  = _scenario_html(data.get("long_scenario",  {}), "LONG – Sekundär / reversal", "#43a047")
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="background:#0d1117;color:#c9d1d9;font-family:Arial,sans-serif;padding:24px;max-width:600px">
  <h1 style="color:#58a6ff;font-size:20px;margin-bottom:4px">{data.get("chart_title","Analys")}</h1>
  <p style="color:#8b949e;margin-top:0">{data.get("instrument_info","")}</p>
  <p><strong style="color:#aab">Nuvarande pris:</strong> {_fmt(data.get("current_price"))}</p>
  <div style="background:#1e2433;border-left:3px solid #58a6ff;padding:10px 14px;margin-bottom:20px;border-radius:0 4px 4px 0">
    <strong>Marknadsläge:</strong> {data.get("market_overview","")}
  </div>
  {short_html}
  {long_html}
  <div style="background:#1e2433;padding:12px 14px;border-radius:4px;margin-top:8px">
    <strong>Sammanfattning:</strong><br>{data.get("summary","")}
  </div>
  <p style="color:#444;font-size:11px;margin-top:24px">Skickad från Daytrading-appen</p>
</body></html>"""


@app.route("/send-email", methods=["POST"])
@login_required
def send_email():
    gmail_user  = os.environ.get("GMAIL_USER", "").strip()
    gmail_pass  = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipient   = os.environ.get("EMAIL_RECIPIENT", "").strip()

    if not gmail_user or not gmail_pass or not recipient:
        return jsonify({"error": "Gmail ej konfigurerad i .env (GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT)"}), 500

    data    = request.get_json(silent=True) or {}
    subject = f"Analys: {data.get('chart_title', 'Daytrading')}"
    html    = _build_email_html(data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        return jsonify({"error": "Gmail-autentisering misslyckades. Kontrollera GMAIL_USER och GMAIL_APP_PASSWORD."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
