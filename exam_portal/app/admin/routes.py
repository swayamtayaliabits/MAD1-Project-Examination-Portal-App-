from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (User, Course, Exam, Rubric, RubricScore, Slot, Booking,
                        EXAM_TYPES, EXAM_TRANSITIONS)
from app.utils import parse_date, parse_int, examiner_has_clash

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@login_required
def only_admin():
    # runs before every route in this file
    if current_user.role != "admin":
        abort(403)

#dashboard code
@admin_bp.route("/")
@admin_bp.route("/dashboard")
def dashboard():
    stats = {
        "courses": Course.query.count(),
        "exams": Exam.query.count(),
        "examiners": User.query.filter_by(role="examiner").count(),
        "students": User.query.filter_by(role="student").count(),
        "slots": Slot.query.count(),
        "bookings": Booking.query.count(),
        "pending_examiners": User.query.filter_by(role="examiner", status="pending").count(),
    }
    return render_template("admin/dashboard.html", stats=stats)

# courses code
def read_course_form(form, course=None):
    """Return (clean data, list of error messages)."""
    errors = []
    code = form.get("code", "").strip().upper()
    name = form.get("name", "").strip()
    status = form.get("status")

    if not code:
        errors.append("Course code is required.")
    if not name:
        errors.append("Course name is required.")
    if status not in ("Active", "Inactive"):
        errors.append("Choose a valid status.")
    clash = Course.query.filter_by(code=code).first()
    if clash and (course is None or clash.id != course.id):
        errors.append("Another course already uses that code.")

    data = {"code": code, "name": name, "status": status,
            "description": form.get("description", "").strip()}
    return data, errors


@admin_bp.route("/courses")
def courses():
    return render_template("admin/courses.html", courses=Course.query.order_by(Course.code).all())


@admin_bp.route("/courses/new", methods=["GET", "POST"])
def course_new():
    if request.method == "POST":
        data, errors = read_course_form(request.form)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/course_form.html", course=None, form=request.form)
        db.session.add(Course(**data))
        db.session.commit()
        flash("Course created.", "success")
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=None, form={})


@admin_bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def course_edit(course_id):
    course = db.get_or_404(Course, course_id)
    if request.method == "POST":
        data, errors = read_course_form(request.form, course)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/course_form.html", course=course, form=request.form)
        for key, value in data.items():
            setattr(course, key, value)
        db.session.commit()
        flash("Course updated.", "success")
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=course, form={})


@admin_bp.route("/courses/<int:course_id>/delete", methods=["POST"])
def course_delete(course_id):
    course = db.get_or_404(Course, course_id)
    if course.exams:
        flash("This course has examinations, so it cannot be removed. Mark it Inactive instead.", "danger")
    else:
        db.session.delete(course)
        db.session.commit()
        flash("Course removed.", "info")
    return redirect(url_for("admin.courses"))

# examinations code
def read_exam_form(form):
    """Validate the exam form. Returns (clean data, list of error messages)."""
    errors = []
    data = {
        "name": form.get("name", "").strip(),
        "exam_type": form.get("exam_type"),
        "course_id": parse_int(form.get("course_id")),
        "duration_minutes": parse_int(form.get("duration_minutes")),
        "max_marks": parse_int(form.get("max_marks")),
        "description": form.get("description", "").strip(),
    }
    if not data["name"]:
        errors.append("Examination name is required.")
    if data["exam_type"] not in EXAM_TYPES:
        errors.append("Choose a valid examination type.")
    if data["course_id"] is None or db.session.get(Course, data["course_id"]) is None:
        errors.append("Choose a valid course.")
    if data["duration_minutes"] is None or data["duration_minutes"] <= 0:
        errors.append("Duration must be a positive whole number of minutes.")
    if data["max_marks"] is None or data["max_marks"] <= 0:
        errors.append("Maximum marks must be a positive whole number.")

    date_fields = {
        "slot_creation_start": "Slot creation start date",
        "slot_creation_end": "Slot creation end date",
        "booking_start": "Booking start date",
        "booking_end": "Booking end date",
    }
    for key, label in date_fields.items():
        data[key] = parse_date(form.get(key))
        if data[key] is None:
            errors.append(f"{label} is required.")

    if not errors:
        if data["slot_creation_end"] < data["slot_creation_start"]:
            errors.append("Slot creation cannot end before it starts.")
        if data["booking_end"] < data["booking_start"]:
            errors.append("Booking cannot end before it starts.")
        if data["booking_start"] < data["slot_creation_start"]:
            errors.append("Booking cannot start before slot creation starts.")
    return data, errors


@admin_bp.route("/exams")
def exams():
    return render_template("admin/exams.html", exams=Exam.query.order_by(Exam.id.desc()).all())


@admin_bp.route("/exams/new", methods=["GET", "POST"])
def exam_new():
    courses = Course.query.filter_by(status="Active").order_by(Course.code).all()
    if request.method == "POST":
        data, errors = read_exam_form(request.form)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/exam_form.html", exam=None, form=request.form,
                                   courses=courses, exam_types=EXAM_TYPES)
        exam = Exam(**data)
        db.session.add(exam)
        db.session.commit()
        flash("Examination created as a Draft. Add rubric criteria and examiners next.", "success")
        return redirect(url_for("admin.exam_detail", exam_id=exam.id))
    return render_template("admin/exam_form.html", exam=None, form={},
                           courses=courses, exam_types=EXAM_TYPES)


@admin_bp.route("/exams/<int:exam_id>/edit", methods=["GET", "POST"])
def exam_edit(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    courses = Course.query.order_by(Course.code).all()
    if request.method == "POST":
        data, errors = read_exam_form(request.form)
        if not errors and data["max_marks"] < exam.rubric_total:
            errors.append(f"Rubric criteria already add up to {exam.rubric_total} marks.")
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/exam_form.html", exam=exam, form=request.form,
                                   courses=courses, exam_types=EXAM_TYPES)
        for key, value in data.items():
            setattr(exam, key, value)
        db.session.commit()
        flash("Examination updated.", "success")
        return redirect(url_for("admin.exam_detail", exam_id=exam.id))
    return render_template("admin/exam_form.html", exam=exam, form={},
                           courses=courses, exam_types=EXAM_TYPES)


@admin_bp.route("/exams/<int:exam_id>")
def exam_detail(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    approved = User.query.filter_by(role="examiner", status="approved").all()
    addable = [e for e in approved if e not in exam.examiners]
    return render_template("admin/exam_detail.html", exam=exam, addable=addable,
                           transitions=EXAM_TRANSITIONS[exam.status])


@admin_bp.route("/exams/<int:exam_id>/delete", methods=["POST"])
def exam_delete(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    if exam.slots:
        flash("This examination already has slots, so it cannot be removed.", "danger")
        return redirect(url_for("admin.exam_detail", exam_id=exam.id))
    db.session.delete(exam)
    db.session.commit()
    flash("Examination removed.", "info")
    return redirect(url_for("admin.exams"))


@admin_bp.route("/exams/<int:exam_id>/status", methods=["POST"])
def exam_status(exam_id):
    """Open or close slot creation / booking by moving the exam to its next status."""
    exam = db.get_or_404(Exam, exam_id)
    new_status = request.form.get("status")
    if new_status not in EXAM_TRANSITIONS[exam.status]:
        flash(f"An examination that is {exam.status} cannot move to {new_status}.", "danger")
    else:
        exam.status = new_status
        db.session.commit()
        flash(f"Examination is now: {new_status}.", "success")
    return redirect(url_for("admin.exam_detail", exam_id=exam.id))


@admin_bp.route("/exams/<int:exam_id>/publish", methods=["POST"])
def exam_publish(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    exam.results_published = not exam.results_published
    db.session.commit()
    flash("Results published." if exam.results_published else "Results hidden again.", "info")
    return redirect(url_for("admin.exam_detail", exam_id=exam.id))


@admin_bp.route("/exams/<int:exam_id>/examiners/add", methods=["POST"])
def exam_examiner_add(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    examiner = db.session.get(User, parse_int(request.form.get("examiner_id")) or 0)
    if examiner is None or examiner.role != "examiner" or examiner.status != "approved":
        flash("Choose an approved examiner.", "danger")
    elif examiner in exam.examiners:
        flash("That examiner is already assigned.", "warning")
    else:
        exam.examiners.append(examiner)
        db.session.commit()
        flash(f"{examiner.name} assigned to this examination.", "success")
    return redirect(url_for("admin.exam_detail", exam_id=exam.id))


@admin_bp.route("/exams/<int:exam_id>/examiners/<int:examiner_id>/remove", methods=["POST"])
def exam_examiner_remove(exam_id, examiner_id):
    exam = db.get_or_404(Exam, exam_id)
    examiner = db.get_or_404(User, examiner_id)
    has_slots = any(s.examiner_id == examiner.id and s.status != "Cancelled" for s in exam.slots)
    if has_slots:
        flash("That examiner already has slots here. Change the slot examiner first.", "danger")
    elif examiner in exam.examiners:
        exam.examiners.remove(examiner)
        db.session.commit()
        flash("Examiner removed from this examination.", "info")
    return redirect(url_for("admin.exam_detail", exam_id=exam.id))

# rubrics  code
def read_rubric_form(form, exam, rubric=None):
    errors = []
    name = form.get("criterion_name", "").strip()
    marks = parse_int(form.get("max_marks"))
    if not name:
        errors.append("Criterion name is required.")
    if marks is None or marks <= 0:
        errors.append("Maximum marks must be a positive whole number.")
    else:
        others = sum(r.max_marks for r in exam.rubrics if rubric is None or r.id != rubric.id)
        if others + marks > exam.max_marks:
            errors.append(f"Criteria would add up to {others + marks}, "
                          f"but the examination is only out of {exam.max_marks}.")
        if rubric is not None and marks != rubric.max_marks:
            if RubricScore.query.filter_by(rubric_id=rubric.id).first():
                errors.append("Marking has started, so the marks of this criterion cannot change.")
    data = {"criterion_name": name, "max_marks": marks,
            "description": form.get("description", "").strip()}
    return data, errors


@admin_bp.route("/exams/<int:exam_id>/rubrics/new", methods=["GET", "POST"])
def rubric_new(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    if request.method == "POST":
        data, errors = read_rubric_form(request.form, exam)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/rubric_form.html", exam=exam, rubric=None, form=request.form)
        db.session.add(Rubric(exam_id=exam.id, **data))
        db.session.commit()
        flash("Criterion added.", "success")
        return redirect(url_for("admin.exam_detail", exam_id=exam.id))
    return render_template("admin/rubric_form.html", exam=exam, rubric=None, form={})


@admin_bp.route("/rubrics/<int:rubric_id>/edit", methods=["GET", "POST"])
def rubric_edit(rubric_id):
    rubric = db.get_or_404(Rubric, rubric_id)
    exam = rubric.exam
    if request.method == "POST":
        data, errors = read_rubric_form(request.form, exam, rubric)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/rubric_form.html", exam=exam, rubric=rubric, form=request.form)
        for key, value in data.items():
            setattr(rubric, key, value)
        db.session.commit()
        flash("Criterion updated.", "success")
        return redirect(url_for("admin.exam_detail", exam_id=exam.id))
    return render_template("admin/rubric_form.html", exam=exam, rubric=rubric, form={})


@admin_bp.route("/rubrics/<int:rubric_id>/delete", methods=["POST"])
def rubric_delete(rubric_id):
    rubric = db.get_or_404(Rubric, rubric_id)
    exam_id = rubric.exam_id
    if RubricScore.query.filter_by(rubric_id=rubric.id).first():
        flash("Marks were already given for this criterion, so it cannot be removed.", "danger")
    else:
        db.session.delete(rubric)
        db.session.commit()
        flash("Criterion removed.", "info")
    return redirect(url_for("admin.exam_detail", exam_id=exam_id))

# examiners and students routing
@admin_bp.route("/examiners")
def examiners():
    people = User.query.filter_by(role="examiner").order_by(User.created_at.desc()).all()
    return render_template("admin/people.html", people=people, kind="Examiners", is_examiner=True)


@admin_bp.route("/students")
def students():
    people = User.query.filter_by(role="student").order_by(User.created_at.desc()).all()
    return render_template("admin/people.html", people=people, kind="Students", is_examiner=False)


@admin_bp.route("/examiners/new", methods=["GET", "POST"])
def examiner_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        errors = []
        if not name or not email or not department:
            errors.append("Name, email and department are required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if email and User.query.filter_by(email=email).first():
            errors.append("That email is already registered.")
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("admin/examiner_form.html", form=request.form)
        user = User(name=name, email=email, department=department,
                    phone=request.form.get("phone", "").strip(),
                    role="examiner", status="approved")   
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Examiner added and approved.", "success")
        return redirect(url_for("admin.examiners"))
    return render_template("admin/examiner_form.html", form={})


@admin_bp.route("/users/<int:user_id>/status", methods=["POST"])
def user_status(user_id):
    """One route for approve / deactivate / activate, for examiners and students."""
    user = db.get_or_404(User, user_id)
    if user.role not in ("examiner", "student"):
        abort(404)
    action = request.form.get("action")
    if action == "approve" and user.role == "examiner":
        user.status = "approved"
    elif action == "deactivate":
        user.status = "deactivated"
    elif action == "activate":
        user.status = "approved" if user.role == "examiner" else "active"
    else:
        flash("That action is not valid here.", "danger")
        return redirect(url_for("admin.dashboard"))
    db.session.commit()
    flash(f"{user.name} is now {user.status}.", "success")
    return redirect(url_for("admin.examiners" if user.role == "examiner" else "admin.students"))

# slot booking
@admin_bp.route("/slots")
def slots():
    exam_id = parse_int(request.args.get("exam_id"))
    query = Slot.query
    if exam_id:
        query = query.filter_by(exam_id=exam_id)
    all_slots = query.order_by(Slot.slot_date, Slot.start_time).all()
    return render_template("admin/slots.html", slots=all_slots,
                           exams=Exam.query.order_by(Exam.name).all(), selected=exam_id)


@admin_bp.route("/slots/<int:slot_id>/examiner", methods=["GET", "POST"])
def slot_examiner(slot_id):
    """Exceptional case: hand a slot (and its booked students) to another examiner."""
    slot = db.get_or_404(Slot, slot_id)
    choices = [e for e in slot.exam.examiners
               if e.status == "approved" and e.id != slot.examiner_id]
    if request.method == "POST":
        new_id = parse_int(request.form.get("examiner_id"))
        new_examiner = next((e for e in choices if e.id == new_id), None)
        if new_examiner is None:
            flash("Choose one of the listed examiners.", "danger")
        elif examiner_has_clash(new_examiner.id, slot.slot_date, slot.start_time, slot.end_time, slot.id):
            flash(f"{new_examiner.name} already has a slot at that time.", "danger")
        else:
            slot.examiner_id = new_examiner.id
            db.session.commit()
            flash(f"Slot now belongs to {new_examiner.name}.", "success")
            return redirect(url_for("admin.slots", exam_id=slot.exam_id))
    return render_template("admin/slot_examiner.html", slot=slot, choices=choices)

# bookings
@admin_bp.route("/bookings")
def bookings():
    exam_id = parse_int(request.args.get("exam_id"))
    status = request.args.get("status", "")
    query = Booking.query
    if exam_id:
        query = query.filter_by(exam_id=exam_id)
    if status in ("Booked", "Cancelled", "Completed"):
        query = query.filter_by(status=status)
    all_bookings = query.order_by(Booking.booking_date.desc()).all()
    return render_template("admin/bookings.html", bookings=all_bookings,
                           exams=Exam.query.order_by(Exam.name).all(),
                           selected=exam_id, selected_status=status)


@admin_bp.route("/bookings/<int:booking_id>/reschedule", methods=["GET", "POST"])
def booking_reschedule(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.status != "Booked":
        flash("Only bookings that are still Booked can be rescheduled.", "warning")
        return redirect(url_for("admin.bookings"))
    choices = [s for s in booking.exam.slots
               if s.id != booking.slot_id and s.status == "Available"]
    if request.method == "POST":
        target = next((s for s in choices if s.id == parse_int(request.form.get("slot_id"))), None)
        if target is None:
            flash("Choose one of the listed slots.", "danger")
        else:
            old_slot = booking.slot
            booking.slot = target
            old_slot.sync_seats()
            target.sync_seats()
            db.session.commit()
            flash("Booking moved to the new slot.", "success")
            return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_reschedule.html", booking=booking, choices=choices)

#search
@admin_bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    found = {"students": [], "examiners": [], "exams": [], "bookings": []}
    if q:
        like = f"%{q}%"
        number = int(q) if q.isdigit() else -1

        def people(role):
            return User.query.filter(
                User.role == role,
                db.or_(User.name.ilike(like), User.email.ilike(like), User.id == number)).all()

        found["students"] = people("student")
        found["examiners"] = people("examiner")
        found["exams"] = Exam.query.filter(
            db.or_(Exam.name.ilike(like), Exam.id == number)).all()
        found["bookings"] = (Booking.query
                             .join(User, Booking.student_id == User.id)
                             .join(Exam, Booking.exam_id == Exam.id)
                             .filter(db.or_(User.name.ilike(like), Exam.name.ilike(like),
                                            Booking.id == number)).all())
    return render_template("admin/search.html", q=q, found=found)

