import os
import asyncio
import concurrent.futures
from flask import Flask, render_template, request, jsonify, session

from admin import admin_bp
from db import init_db

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "valr-bot-dev-key-change-in-prod")


with app.app_context():
    init_db()

app.register_blueprint(admin_bp)

from vac_bot.chain import ask

def _run_async(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)

@app.route("/")
def index():
    return render_template("vac_chat.html")

@app.route("/ask", methods=["POST"])
def ask_question():
    q = request.json.get("question", "").strip()
    if not q:
        return jsonify({"error": "Question is required"}), 400

    session.permanent = True
    sid = session.get("session_id")
    if not sid:
        sid = request.remote_addr or "default"
        session["session_id"] = sid

    result = _run_async(ask(q, sid))
    return jsonify(result)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
