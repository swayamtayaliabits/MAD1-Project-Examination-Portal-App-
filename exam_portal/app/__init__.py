import os
from datetime import date

from flask import Flask, render_template

from config import Config
from app.extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User
    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp
    from app.examiner.routes import examiner_bp
    from app.student.routes import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(examiner_bp)
    app.register_blueprint(student_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.context_processor
    def inject_today():
        return {"today": date.today()}

    with app.app_context():
        db.create_all()      # builds every table from models.py
        create_admin(app)    

    return app


def create_admin(app):
    from app.models import User

    if User.query.filter_by(role="admin").first():
        return
    admin = User(name=app.config["ADMIN_NAME"], email=app.config["ADMIN_EMAIL"],
                 role="admin", status="active")
    admin.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()