import hmac
import secrets

from flask import Flask, jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.routes_scan import scan_bp
from app.routes_admin import admin_bp

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.context_processor
    def csrf_context():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return {"csrf_token": token}

    @app.before_request
    def protect_state_changing_requests():
        if app.config["FORCE_HTTPS"] and not request.is_secure:
            return ("HTTPS is required.", 400)
        if request.method != "POST":
            return None
        token = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(token, supplied):
            return jsonify({"ok": False, "message": "CSRF validation failed."}), 403
        return None

    app.register_blueprint(scan_bp)
    app.register_blueprint(admin_bp)

    return app
