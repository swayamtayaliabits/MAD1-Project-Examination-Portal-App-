from flask import Blueprint

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
def dashboard():
    return "Student dashboard (temporary)"

from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user

from app.extensions import db
from app.models import Course, Exam, Slot, Booking, EXAM_TYPES
from app.decorators import role_required
from app.utils import parse_int

student_bp = Blueprint("student", __name__, url_prefix="/student")


def open_exams():
    """Examinations a student can currently book (admin opened booking AND dates fit)."""
    exams = (Exam.query.join(Course).filter(Exam.status == "Booking Open", Course.status == "Active")
             .order_by(Exam.name).all())
    return [e for e in exams if e.booking_open]


@student_bp.route("/dashboard")
@role_required("student")
def dashboard():
    exams = open_exams()
    available_slots = [s for e in exams for s in e.slots if s.status == "Available"]
    mine = (Booking.query.filter_by(student_id=current_user.id)
            .order_by(Booking.booking_date.desc()).all())
    booked = [b for b in mine if b.status == "Booked"]
    upcoming = sorted([b for b in booked if b.slot.slot_date >= date.today()],
                      key=lambda b: (b.slot.slot_date, b.slot.start_time))
    results = [b for b in mine if b.evaluation and b.exam.results_published]
    return render_template("student/dashboard.html", exams=exams, available_slots=available_slots,
                           booked=booked, upcoming=upcoming, results=results)


@student_bp.route("/exams")
@role_required("student")
def exams():
    q = request.args.get("q", "").strip().lower()
    exam_type = request.args.get("exam_type", "")
    course_id = parse_int(request.args.get("course_id"))

    found = open_exams()
    if q:
        found = [e for e in found if q in e.name.lower() or q in e.course.name.lower()
                 or q in e.course.code.lower()]
    if exam_type in EXAM_TYPES:
        found = [e for e in found if e.exam_type == exam_type]
    if course_id:
        found = [e for e in found if e.course_id == course_id]
    return render_template("student/exams.html", exams=found, q=q, exam_type=exam_type,
                           course_id=course_id, exam_types=EXAM_TYPES,
                           courses=Course.query.filter_by(status="Active").order_by(Course.code).all())


@student_bp.route("/exams/<int:exam_id>")
@role_required("student")
def exam_detail(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    if exam.status == "Draft":
        abort(404)
    slots = sorted([s for s in exam.slots if s.status != "Cancelled"],
                   key=lambda s: (s.slot_date, s.start_time))
    mine = Booking.query.filter(Booking.student_id == current_user.id, Booking.exam_id == exam.id,
                                Booking.status.in_(["Booked", "Completed"])).first()
    return render_template("student/exam_detail.html", exam=exam, slots=slots, my_booking=mine)


@student_bp.route("/slots/<int:slot_id>/book", methods=["POST"])
@role_required("student")
def book_slot(slot_id):
    slot = db.get_or_404(Slot, slot_id)
    exam = slot.exam
    back = redirect(url_for("student.exam_detail", exam_id=exam.id))

    if not exam.booking_open:
        flash("Booking is not open for this examination right now.", "danger")
        return back
    if slot.status != "Available" or slot.available_seats <= 0:
        flash("That slot is full or no longer available.", "danger")
        return back
    already = Booking.query.filter(Booking.student_id == current_user.id, Booking.exam_id == exam.id,
                                   Booking.status.in_(["Booked", "Completed"])).first()
    if already:
        flash("You have already booked this examination.", "warning")
        return back

    booking = Booking(student_id=current_user.id, exam_id=exam.id, slot=slot)
    db.session.add(booking)
    slot.sync_seats()           # takes a seat; marks the slot Full when none are left
    db.session.commit()
    flash("Slot booked.", "success")
    return redirect(url_for("student.bookings"))


@student_bp.route("/bookings")
@role_required("student")
def bookings():
    mine = (Booking.query.filter_by(student_id=current_user.id)
            .order_by(Booking.booking_date.desc()).all())
    return render_template("student/bookings.html", bookings=mine)


@student_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@role_required("student")
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.student_id != current_user.id:
        abort(403)
    if booking.status != "Booked":
        flash("Only active bookings can be cancelled.", "warning")
    elif booking.exam.booking_deadline_passed or booking.exam.status == "Completed":
        flash("The booking deadline has passed, so this booking can no longer be cancelled.", "danger")
    else:
        booking.status = "Cancelled"
        booking.slot.sync_seats()   # gives the seat back, reopens a Full slot
        db.session.commit()
        flash("Booking cancelled.", "info")
    return redirect(url_for("student.bookings"))


@student_bp.route("/results/<int:booking_id>")
@role_required("student")
def result(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.student_id != current_user.id:
        abort(403)
    if not (booking.evaluation and booking.exam.results_published):
        flash("The result for this examination has not been published yet.", "warning")
        return redirect(url_for("student.bookings"))
    return render_template("student/result.html", booking=booking)


@student_bp.route("/profile", methods=["GET", "POST"])
@role_required("student")
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name cannot be empty.", "danger")
        else:
            current_user.name = name
            current_user.phone = request.form.get("phone", "").strip()
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("student.profile"))
    return render_template("student/profile.html")
