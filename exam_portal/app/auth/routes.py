from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def go_to_dashboard(user):
    """Send each role to its own dashboard."""
    if user.role == "admin":
        return redirect(url_for("admin.dashboard"))
    if user.role == "examiner":
        return redirect(url_for("examiner.dashboard"))
    return redirect(url_for("student.dashboard"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return go_to_dashboard(current_user)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "student")

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email:
            errors.append("Email is required.")
        elif User.query.filter_by(email=email).first():
            errors.append("That email is already registered.")
        if role not in ("examiner", "student"):
            errors.append("Choose examiner or student.")
        if role == "examiner" and not department:
            errors.append("Examiners must enter a department.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("auth/register.html", form=request.form)

        user = User(name=name, email=email, phone=phone, department=department, role=role,
                    status="pending" if role == "examiner" else "active")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        if role == "examiner":
            flash("Registered. The admin must approve your account before you can log in.", "info")
        else:
            flash("Registered. You can log in now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form={})


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return go_to_dashboard(current_user)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash("Wrong email or password.", "danger")
        elif user.status == "deactivated":
            flash("This account has been deactivated. Contact the admin.", "danger")
        elif user.status == "pending":
            flash("Your examiner account is still waiting for admin approval.", "warning")
        else:
            login_user(user)
            flash(f"Welcome, {user.name}.", "success")
            return go_to_dashboard(user)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You are logged out.", "info")
    return redirect(url_for("auth.login"))