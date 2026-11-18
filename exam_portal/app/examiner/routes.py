from flask import Blueprint

examiner_bp = Blueprint("examiner", __name__, url_prefix="/examiner")


@examiner_bp.route("/dashboard")
def dashboard():
    return "Examiner dashboard (temporary)"

from datetime import date, datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user

from app.extensions import db
from app.models import Exam, Slot, Booking, Evaluation, RubricScore
from app.decorators import role_required
from app.utils import parse_date, parse_time, parse_int, examiner_has_clash

examiner_bp = Blueprint("examiner", __name__, url_prefix="/examiner")


def exam_for_me(exam_id):
    """Fetch an exam, but only if the admin assigned it to the logged-in examiner."""
    exam = db.get_or_404(Exam, exam_id)
    if current_user.id not in [e.id for e in exam.examiners]:
        abort(403)
    return exam


def my_slot(slot_id):
    """Fetch a slot, but only if it belongs to the logged-in examiner."""
    slot = db.get_or_404(Slot, slot_id)
    if slot.examiner_id != current_user.id:
        abort(403)
    return slot


@examiner_bp.route("/dashboard")
@role_required("examiner")
def dashboard():
    live_slots = (Slot.query.filter(Slot.examiner_id == current_user.id, Slot.status != "Cancelled")
                  .order_by(Slot.slot_date, Slot.start_time).all())
    students_booked = sum(len(s.active_bookings) for s in live_slots)
    pending = sum(1 for s in live_slots for b in s.bookings if b.status == "Booked")
    return render_template("examiner/dashboard.html", exams=current_user.assigned_exams,
                           slots=live_slots, students_booked=students_booked, pending=pending)


@examiner_bp.route("/exams/<int:exam_id>")
@role_required("examiner")
def exam_detail(exam_id):
    exam = exam_for_me(exam_id)
    slots = (Slot.query.filter_by(exam_id=exam.id, examiner_id=current_user.id)
             .order_by(Slot.slot_date, Slot.start_time).all())
    return render_template("examiner/exam_detail.html", exam=exam, slots=slots)


def read_slot_form(form, exam, slot=None):
    """Validate the slot form. Returns (clean data, list of error messages)."""
    errors = []
    data = {
        "slot_date": parse_date(form.get("slot_date")),
        "start_time": parse_time(form.get("start_time")),
        "end_time": parse_time(form.get("end_time")),
        "capacity": parse_int(form.get("capacity")),
    }
    if data["slot_date"] is None:
        errors.append("Enter a valid date.")
    elif data["slot_date"] < date.today():
        errors.append("The slot date cannot be in the past.")
    if data["start_time"] is None or data["end_time"] is None:
        errors.append("Enter a valid start and end time.")
    elif data["end_time"] <= data["start_time"]:
        errors.append("End time must be after start time.")
    if data["capacity"] is None or data["capacity"] < 1:
        errors.append("Capacity must be at least 1.")
    elif slot is not None and data["capacity"] < len(slot.active_bookings):
        errors.append(f"{len(slot.active_bookings)} students are already booked, "
                      f"so capacity cannot go below that.")
    if not errors and examiner_has_clash(current_user.id, data["slot_date"], data["start_time"],
                                         data["end_time"], slot.id if slot else None):
        errors.append("You already have another slot overlapping that time.")
    return data, errors


@examiner_bp.route("/exams/<int:exam_id>/slots/new", methods=["GET", "POST"])
@role_required("examiner")
def slot_new(exam_id):
    exam = exam_for_me(exam_id)
    if not exam.slot_creation_open:
        flash("Slot creation is not open for this examination right now.", "danger")
        return redirect(url_for("examiner.exam_detail", exam_id=exam.id))
    if request.method == "POST":
        data, errors = read_slot_form(request.form, exam)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("examiner/slot_form.html", exam=exam, slot=None, form=request.form)
        slot = Slot(exam_id=exam.id, examiner_id=current_user.id,
                    available_seats=data["capacity"], status="Available", **data)
        db.session.add(slot)
        db.session.commit()
        flash("Slot created.", "success")
        return redirect(url_for("examiner.exam_detail", exam_id=exam.id))
    return render_template("examiner/slot_form.html", exam=exam, slot=None, form={})


@examiner_bp.route("/slots/<int:slot_id>/edit", methods=["GET", "POST"])
@role_required("examiner")
def slot_edit(slot_id):
    slot = my_slot(slot_id)
    exam = slot.exam
    if not exam.slot_creation_open or slot.status == "Cancelled":
        flash("Slots can only be changed while slot creation is open.", "danger")
        return redirect(url_for("examiner.exam_detail", exam_id=exam.id))
    if request.method == "POST":
        data, errors = read_slot_form(request.form, exam, slot)
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("examiner/slot_form.html", exam=exam, slot=slot, form=request.form)
        for key, value in data.items():
            setattr(slot, key, value)
        slot.sync_seats()
        db.session.commit()
        flash("Slot updated.", "success")
        return redirect(url_for("examiner.exam_detail", exam_id=exam.id))
    return render_template("examiner/slot_form.html", exam=exam, slot=slot, form={})


@examiner_bp.route("/slots/<int:slot_id>/delete", methods=["POST"])
@role_required("examiner")
def slot_delete(slot_id):
    slot = my_slot(slot_id)
    if not slot.exam.slot_creation_open:
        flash("Slots can only be removed while slot creation is open.", "danger")
    elif slot.active_bookings:
        flash("Students have booked this slot, so it cannot be removed.", "danger")
    else:
        slot.status = "Cancelled"     # kept in the database so history is not lost
        db.session.commit()
        flash("Slot removed.", "info")
    return redirect(url_for("examiner.exam_detail", exam_id=slot.exam_id))


@examiner_bp.route("/slots/<int:slot_id>/students")
@role_required("examiner")
def slot_students(slot_id):
    slot = my_slot(slot_id)
    return render_template("examiner/slot_students.html", slot=slot)

# ------------------------------------------------------------- evaluation
@examiner_bp.route("/bookings/<int:booking_id>/evaluate", methods=["GET", "POST"])
@role_required("examiner")
def evaluate(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.slot.examiner_id != current_user.id:    # only students in MY slots
        abort(403)
    exam = booking.exam
    back = redirect(url_for("examiner.slot_students", slot_id=booking.slot_id))

    if booking.status == "Cancelled":
        flash("This booking was cancelled.", "warning")
        return back
    if exam.results_published:
        flash("Results are published, so marks can no longer change.", "warning")
        return back
    if not exam.rubrics:
        flash("The admin has not defined rubric criteria for this examination yet.", "warning")
        return back

    evaluation = booking.evaluation
    given = {s.rubric_id: s.marks for s in evaluation.scores} if evaluation else {}
    remarks = evaluation.remarks if evaluation else ""

    if request.method == "POST":
        scores, errors = {}, []
        for rubric in exam.rubrics:
            value = parse_int(request.form.get(f"score_{rubric.id}"))
            if value is None or value < 0 or value > rubric.max_marks:
                errors.append(f"{rubric.criterion_name}: enter a whole number from 0 to {rubric.max_marks}.")
            else:
                scores[rubric.id] = value
        remarks = request.form.get("remarks", "").strip()

        if errors:
            for message in errors:
                flash(message, "danger")
            given = {rid: request.form.get(f"score_{rid}") for rid in [r.id for r in exam.rubrics]}
        else:
            if evaluation is None:
                evaluation = Evaluation(booking=booking, examiner_id=current_user.id)
                db.session.add(evaluation)
            else:
                evaluation.scores.clear()
            for rubric_id, marks in scores.items():
                evaluation.scores.append(RubricScore(rubric_id=rubric_id, marks=marks))
            evaluation.total_marks = sum(scores.values())
            evaluation.remarks = remarks
            evaluation.evaluated_at = datetime.now()
            booking.status = "Completed"
            if not any(b.status == "Booked" for b in booking.slot.bookings):
                booking.slot.status = "Completed"
            db.session.commit()
            flash("Marks and remarks saved.", "success")
            return back

    return render_template("examiner/evaluate.html", booking=booking, rubrics=exam.rubrics,
                           given=given, remarks=remarks)