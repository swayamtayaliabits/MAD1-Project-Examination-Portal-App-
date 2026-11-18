from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

EXAM_TYPES = ("Viva", "Practical", "Project Demo", "Assessment")
EXAM_STATUSES = ("Draft", "Slot Creation", "Booking Open", "Closed", "Completed")

# Which statuses an exam is allowed to move to from its current status.
EXAM_TRANSITIONS = {
    "Draft": ["Slot Creation"],
    "Slot Creation": ["Booking Open", "Closed"],
    "Booking Open": ["Closed"],
    "Closed": ["Slot Creation", "Booking Open", "Completed"],
    "Completed": [],
}

# Many to many: one exam can have many examiners and one examiner can have many exams 
exam_examiners = db.Table(
    "exam_examiners",
    db.Column("exam_id", db.Integer, db.ForeignKey("exams.id"), primary_key=True),
    db.Column("examiner_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class User(UserMixin, db.Model):
    """One table for admin, examiners and students. The role column tells them apart.
    status: examiner -> pending / approved / deactivated
            student  -> active / deactivated
            admin    -> active"""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    department = db.Column(db.String(100))
    role = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    slots = db.relationship("Slot", back_populates="examiner")
    bookings = db.relationship("Booking", back_populates="student")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="Active")

    exams = db.relationship("Exam", back_populates="course")


class Exam(db.Model):
    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    exam_type = db.Column(db.String(30), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    max_marks = db.Column(db.Integer, nullable=False)
    slot_creation_start = db.Column(db.Date, nullable=False)
    slot_creation_end = db.Column(db.Date, nullable=False)
    booking_start = db.Column(db.Date, nullable=False)
    booking_end = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Draft")
    results_published = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.Text)

    course = db.relationship("Course", back_populates="exams")
    rubrics = db.relationship("Rubric", back_populates="exam", cascade="all, delete-orphan")
    slots = db.relationship("Slot", back_populates="exam")
    examiners = db.relationship("User", secondary=exam_examiners, backref="assigned_exams")

    @property
    def slot_creation_open(self):
        """Examiners may create slots only if the admin opened slot creation
        AND today falls inside the slot creation dates."""
        return (self.status == "Slot Creation"
                and self.slot_creation_start <= date.today() <= self.slot_creation_end)

    @property
    def booking_open(self):
        """Students may book only if the admin opened booking
        AND today falls inside the booking dates."""
        return (self.status == "Booking Open"
                and self.booking_start <= date.today() <= self.booking_end)

    @property
    def booking_deadline_passed(self):
        return date.today() > self.booking_end

    @property
    def rubric_total(self):
        return sum(r.max_marks for r in self.rubrics)


class Rubric(db.Model):
    __tablename__ = "rubrics"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    criterion_name = db.Column(db.String(150), nullable=False)
    max_marks = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)

    exam = db.relationship("Exam", back_populates="rubrics")

    @property
    def weightage(self):
        """Share of the exam's total marks, worked out on the fly so it can never go stale."""
        if not self.exam.max_marks:
            return 0
        return round(self.max_marks / self.exam.max_marks * 100, 1)


class Slot(db.Model):
    __tablename__ = "slots"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    slot_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=1)
    available_seats = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="Available")

    exam = db.relationship("Exam", back_populates="slots")
    examiner = db.relationship("User", back_populates="slots")
    bookings = db.relationship("Booking", back_populates="slot")

    @property
    def active_bookings(self):
        """Bookings that still occupy a seat (everything except Cancelled)."""
        return [b for b in self.bookings if b.status != "Cancelled"]

    def sync_seats(self):
        """Recalculate seats and status from the real bookings.
        Full when no seats are left, Available again when a seat frees up."""
        if self.status in ("Cancelled", "Completed"):
            return
        self.available_seats = self.capacity - len(self.active_bookings)
        self.status = "Full" if self.available_seats <= 0 else "Available"


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("slots.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), nullable=False, default="Booked")

    student = db.relationship("User", back_populates="bookings")
    slot = db.relationship("Slot", back_populates="bookings")
    exam = db.relationship("Exam")
    evaluation = db.relationship("Evaluation", back_populates="booking", uselist=False)


class Evaluation(db.Model):
    """One evaluation per booking: the examiner's total and remarks."""
    __tablename__ = "evaluations"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    total_marks = db.Column(db.Integer, default=0)
    remarks = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime, default=datetime.now)

    booking = db.relationship("Booking", back_populates="evaluation")
    examiner = db.relationship("User")
    scores = db.relationship("RubricScore", back_populates="evaluation",
                             cascade="all, delete-orphan")


class RubricScore(db.Model):
    """Marks given for one rubric criterion inside one evaluation."""
    __tablename__ = "rubric_scores"

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("evaluations.id"), nullable=False)
    rubric_id = db.Column(db.Integer, db.ForeignKey("rubrics.id"), nullable=False)
    marks = db.Column(db.Integer, nullable=False)

    evaluation = db.relationship("Evaluation", back_populates="scores")
    rubric = db.relationship("Rubric")