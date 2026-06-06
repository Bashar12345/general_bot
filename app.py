import os
import asyncio
import concurrent.futures
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, session, g, redirect, url_for, flash

from admin import admin_bp
from db import init_db, get_settings, get_default_tenant_id, get_conn
from services.auth_service import AuthService

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "valr-bot-dev-key-change-in-prod")

with app.app_context():
    init_db()

app.register_blueprint(admin_bp)

from vac_bot.chain import ask

auth_service = AuthService()


@app.before_request
def set_tenant_context():
    tenant_id = session.get("tenant_id")
    if tenant_id is None:
        tenant_id = get_default_tenant_id()
    g.tenant_id = tenant_id


def _run_async(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


@app.route("/")
def index():
    settings = get_settings(g.tenant_id)
    bot_name = settings.get("bot_name", "b2b bots")
    if auth_service.is_logged_in():
        theme = (settings.get("theme") or "dark").strip().lower()
        if theme not in {"dark", "light"}:
            theme = "dark"
        return render_template(
            "vac_chat.html",
            bot_name=bot_name,
            bot_tagline=f"Intelligent Enterprise Assistant — {bot_name}",
            theme=theme,
        )
    return render_template(
        "landing.html",
        now=datetime.now(timezone.utc),
    )


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
    result = _run_async(ask(q, sid, tenant_id=g.tenant_id))
    return jsonify(result)


@app.route('/login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        if not username or not password:
            flash('Username and password required', 'error')
            return redirect(url_for('user_login'))
        result = auth_service.login_user(username, password)
        if result.success:
            flash('Logged in', 'success')
            return redirect(url_for('index'))
        flash('Invalid credentials', 'error')
    return render_template('user/login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        business = (request.form.get('business_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = (request.form.get('password') or '').strip()
        result = auth_service.signup(business, email, password)
        if result.success:
            flash('Account created! Welcome to b2b bots.', 'success')
            return redirect(url_for('index'))
        flash(result.error, 'error')
        return redirect(url_for('signup'))
    return render_template('user/signup.html')


@app.route('/logout', methods=['POST'])
def user_logout():
    auth_service.logout_user()
    return redirect(url_for('user_login'))


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if not auth_service.is_logged_in():
        flash('Login required', 'error')
        return redirect(url_for('user_login'))
    if request.method == 'POST':
        current = (request.form.get('current') or '').strip()
        newpw = (request.form.get('new') or '').strip()
        if not current or not newpw:
            flash('Both current and new password are required', 'error')
            return redirect(url_for('change_password'))
        ok, msg = auth_service.change_password(session['user_id'], current, newpw)
        flash(msg, 'success' if ok else 'error')
        if ok:
            return redirect(url_for('index'))
    return render_template('user/change_password.html')


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
