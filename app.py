from __future__ import annotations

import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from functools import wraps
from typing import Callable, TypeVar

from flask import Flask, flash, redirect, render_template, request, session, url_for

from db import close_db, get_db, init_db, query_all, query_one


R = TypeVar("R")


WEEKDAYS_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


@dataclass(frozen=True)
class Schedule:
    weekday: int
    is_open: bool
    start_time: str
    end_time: str
    max_seats: int


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    init_db()

    @app.before_request
    def _cleanup() -> None:
        cleanup_old_bookings()

    @app.route("/", methods=["GET", "POST"])
    def index():
        today = date.today()
        weekday = today.weekday()
        schedule = get_schedule(weekday)
        seats_left = get_seats_left(today, schedule.max_seats) if schedule.is_open else 0

        if request.method == "POST":
            if not schedule.is_open:
                flash("Сегодня запись закрыта.", "danger")
                return redirect(url_for("index"))
            if seats_left <= 0:
                flash("Мест больше нет.", "danger")
                return redirect(url_for("index"))

            student_name = (request.form.get("student_name") or "").strip()
            parent_name = (request.form.get("parent_name") or "").strip()
            group_number = (request.form.get("group_number") or "").strip()
            parent_phone = (request.form.get("parent_phone") or "").strip()

            if not student_name or not parent_name or not parent_phone:
                flash("Заполните обязательные поля.", "danger")
                return redirect(url_for("index"))

            if not is_phone_valid(parent_phone):
                flash("Телефон выглядит некорректно. Пример: +7 999 123-45-67", "danger")
                return redirect(url_for("index"))

            ok, reason = try_create_booking(
                booking_date=today.isoformat(),
                student_name=student_name,
                parent_name=parent_name,
                group_number=group_number or None,
                parent_phone=parent_phone,
                max_seats=schedule.max_seats,
            )
            if ok:
                flash("Вы успешно записаны.", "success")
            elif reason == "duplicate":
                flash("Вы уже записаны на сегодня.", "danger")
            else:
                flash("Мест больше нет.", "danger")
            return redirect(url_for("index"))

        return render_template(
            "index.html",
            weekday_name=WEEKDAYS_RU.get(weekday, str(weekday)),
            schedule=schedule,
            seats_left=seats_left,
        )

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        if request.method == "POST":
            user = (request.form.get("user") or "").strip()
            password = (request.form.get("password") or "").strip()
            if check_admin_credentials(user, password):
                session["is_admin"] = True
                flash("Вход выполнен.", "success")
                return redirect(url_for("admin_dashboard"))
            flash("Неверный логин или пароль.", "danger")
        return render_template("admin_login.html")

    @app.route("/admin/logout", methods=["POST"])
    @admin_required
    def admin_logout():
        session.pop("is_admin", None)
        flash("Вы вышли из админ‑панели.", "info")
        return redirect(url_for("index"))

    @app.route("/admin/", methods=["GET"])
    @admin_required
    def admin_dashboard():
        today = date.today()
        weekday = today.weekday()
        schedules = [row_to_schedule(r) for r in query_all("SELECT * FROM schedule ORDER BY weekday;")]
        today_schedule = get_schedule(weekday)
        today_bookings = query_all(
            "SELECT * FROM bookings WHERE booking_date = ? ORDER BY id DESC;",
            (today.isoformat(),),
        )
        seats_left = get_seats_left(today, today_schedule.max_seats) if today_schedule.is_open else 0
        return render_template(
            "admin.html",
            schedules=schedules,
            weekday_today=weekday,
            weekday_today_name=WEEKDAYS_RU.get(weekday, str(weekday)),
            seats_left=seats_left,
            today_schedule=today_schedule,
            today_bookings=today_bookings,
            today_date=today.isoformat(),
            weekdays_ru=WEEKDAYS_RU,
        )

    @app.route("/admin/schedule", methods=["POST"])
    @admin_required
    def admin_update_schedule():
        db = get_db()
        for weekday in range(7):
            is_open = 1 if request.form.get(f"is_open_{weekday}") == "on" else 0
            start_time = (request.form.get(f"start_time_{weekday}") or "18:00").strip()
            end_time = (request.form.get(f"end_time_{weekday}") or "19:20").strip()
            max_seats_raw = (request.form.get(f"max_seats_{weekday}") or "20").strip()
            try:
                max_seats = max(0, int(max_seats_raw))
            except ValueError:
                max_seats = 20

            if not is_time_hhmm(start_time):
                start_time = "18:00"
            if not is_time_hhmm(end_time):
                end_time = "19:20"

            db.execute(
                """
                UPDATE schedule
                SET is_open = ?, start_time = ?, end_time = ?, max_seats = ?
                WHERE weekday = ?;
                """,
                (is_open, start_time, end_time, max_seats, weekday),
            )
        db.commit()
        flash("Настройки расписания сохранены.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/bookings/<int:booking_id>/delete", methods=["POST"])
    @admin_required
    def admin_delete_booking(booking_id: int):
        db = get_db()
        db.execute("DELETE FROM bookings WHERE id = ?;", (booking_id,))
        db.commit()
        flash("Запись удалена.", "info")
        return redirect(url_for("admin_dashboard"))

    app.teardown_appcontext(close_db)
    return app


def admin_required(fn: Callable[..., R]) -> Callable[..., R]:
    @wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)

    return wrapper


def check_admin_credentials(user: str, password: str) -> bool:
    env_user = os.environ.get("ADMIN_USER", "admin")
    env_password = os.environ.get("ADMIN_PASSWORD", "admin")
    return secrets.compare_digest(user, env_user) and secrets.compare_digest(password, env_password)


def is_time_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"[0-2]\d:[0-5]\d", value)) and value[:2] <= "23"


def is_phone_valid(phone: str) -> bool:
    digits = re.sub(r"\D+", "", phone)
    return 10 <= len(digits) <= 15


def row_to_schedule(row) -> Schedule:  # sqlite3.Row
    return Schedule(
        weekday=int(row["weekday"]),
        is_open=bool(row["is_open"]),
        start_time=str(row["start_time"]),
        end_time=str(row["end_time"]),
        max_seats=int(row["max_seats"]),
    )


def get_schedule(weekday: int) -> Schedule:
    row = query_one("SELECT * FROM schedule WHERE weekday = ?;", (weekday,))
    if row is None:
        return Schedule(weekday=weekday, is_open=True, start_time="18:00", end_time="19:20", max_seats=20)
    return row_to_schedule(row)


def get_seats_left(day: date, max_seats: int) -> int:
    row = query_one("SELECT COUNT(*) AS c FROM bookings WHERE booking_date = ?;", (day.isoformat(),))
    taken = int(row["c"]) if row else 0
    return max(0, max_seats - taken)


def try_create_booking(
    *,
    booking_date: str,
    student_name: str,
    parent_name: str,
    group_number: str | None,
    parent_phone: str,
    max_seats: int,
) -> tuple[bool, str]:
    db = get_db()
    db.execute("BEGIN IMMEDIATE;")
    taken_row = db.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE booking_date = ?;",
        (booking_date,),
    ).fetchone()
    taken = int(taken_row["c"]) if taken_row else 0
    if taken >= max_seats:
        db.execute("ROLLBACK;")
        return False, "no_seats"

    try:
        db.execute(
            """
            INSERT INTO bookings (booking_date, created_at, student_name, parent_name, group_number, parent_phone)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                booking_date,
                datetime.now().isoformat(timespec="seconds"),
                student_name,
                parent_name,
                group_number,
                parent_phone,
            ),
        )
        db.execute("COMMIT;")
        return True, "ok"
    except sqlite3.IntegrityError:
        db.execute("ROLLBACK;")
        return False, "duplicate"


def cleanup_old_bookings() -> None:
    today = date.today().isoformat()
    db = get_db()
    db.execute("DELETE FROM bookings WHERE booking_date < ?;", (today,))
    db.commit()


if __name__ == "__main__":
    init_db()
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
