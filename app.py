import os
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, session, g, redirect, url_for, flash

from admin import admin_bp
from db import init_db, get_settings, get_default_tenant_id, get_conn
from api.flask.adapters import FlaskSessionProvider
from api import AuthHandler, ChatHandler

session_provider = FlaskSessionProvider()
auth_handler = AuthHandler(session_provider)
chat_handler = ChatHandler(session_provider)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "valr-bot-dev-key-change-in-prod")

with app.app_context():
    init_db()

app.register_blueprint(admin_bp)

DEFAULT_BOT_NAME = "b2b bots"


@app.before_request
def set_tenant_context():
    tenant_id = session.get("tenant_id")
    if tenant_id is None:
        tenant_id = get_default_tenant_id()
    g.tenant_id = tenant_id


@app.context_processor
def inject_globals():
    bot_name = DEFAULT_BOT_NAME
    tid = session.get("tenant_id")
    if tid:
        settings = get_settings(tid)
        bot_name = settings.get("bot_name") or DEFAULT_BOT_NAME
    return {"admin_brand_name": bot_name, "is_logged_in": auth_handler.is_logged_in()}


@app.route("/")
def index():
    settings = get_settings(g.tenant_id)
    bot_name = settings.get("bot_name", "b2b bots")
    if auth_handler.is_logged_in():
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
    from api.dto import ChatRequest
    result = chat_handler.ask_question(ChatRequest(question=q, session_id=sid, tenant_id=g.tenant_id))
    if result.success:
        return jsonify({"answer": result.answer, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "total_tokens": result.total_tokens})
    return jsonify({"error": result.error}), 400


@app.route('/login', methods=['GET', 'POST'])
def user_login():
    if auth_handler.is_logged_in():
        return redirect(url_for('index'))
    if request.method == 'POST':
        from api.dto import LoginRequest
        result = auth_handler.login(LoginRequest(
            username=(request.form.get('username') or '').strip(),
            password=(request.form.get('password') or '').strip(),
        ))
        if result.success:
            return redirect(url_for('index'))
        flash(result.error, 'error')
    return render_template('user/login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        from api.dto import SignupRequest
        result = auth_handler.signup(SignupRequest(
            business_name=(request.form.get('business_name') or '').strip(),
            email=(request.form.get('email') or '').strip().lower(),
            password=(request.form.get('password') or '').strip(),
        ))
        if result.success:
            flash('Account created! Welcome to b2b bots.', 'success')
            return redirect(url_for('index'))
        flash(result.error, 'error')
        return redirect(url_for('signup'))
    return render_template('user/signup.html')


@app.route('/logout', methods=['POST'])
def user_logout():
    auth_handler.logout()
    return redirect(url_for('user_login'))


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if not auth_handler.is_logged_in():
        flash('Login required', 'error')
        return redirect(url_for('user_login'))
    if request.method == 'POST':
        from api.dto import ChangePasswordRequest
        result = auth_handler.change_password(ChangePasswordRequest(
            user_id=session['user_id'],
            current_password=(request.form.get('current') or '').strip(),
            new_password=(request.form.get('new') or '').strip(),
        ))
        flash(result.error or 'Password updated', 'success' if result.success else 'error')
        if result.success:
            return redirect(url_for('index'))
    return render_template('user/change_password.html')


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
