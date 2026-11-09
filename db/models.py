from sqlalchemy import BigInteger, String, ForeignKey, DateTime, func, Integer, Boolean, UniqueConstraint, Text, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from typing import List, Optional
from datetime import datetime, date
from db.base import Base

# ---------------- USERS & ROLES ----------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True) # автоінкремент
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False) # ідентифікатор користувача
    user_name: Mapped[str] = mapped_column(String(255)) # ім'я
    user_surname: Mapped[Optional[str]] = mapped_column(String(255)) # прізвище
    username: Mapped[Optional[str]] = mapped_column(String(255)) # нікнейм
    visit: Mapped[int] = mapped_column(default=0) # кількість відвідувань
    number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Номер за журналом
    viber: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="user", cascade="all, delete-orphan",
                                                   lazy="selectin")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    users: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role")


class UserRole(Base):
    __tablename__ = "user_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))

    user: Mapped["User"] = relationship("User", back_populates="roles")
    role: Mapped["Role"] = relationship("Role", back_populates="users", lazy="selectin")
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)


# ---------------- ACADEMIC CORE ----------------

class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Унікальний ID предмета
    name: Mapped[str] = mapped_column(String(255))  # Назва навчальної дисципліни
    # ID викладача з таблиці users
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    teacher_name: Mapped[str] = mapped_column(String(255))  # Прізвище та ініціали викладача

    # Поля для дистанційного навчання (Zoom)
    zoom_link: Mapped[Optional[str]] = mapped_column(String(500))  # Пряме посилання на конференцію
    zoom_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Ідентифікатор конференції (Meeting ID)
    zoom_password: Mapped[Optional[str]] = mapped_column(String(100))  # Код доступу (пароль) конференції

    # Відносини з іншими таблицями
    lessons: Mapped[List["Lesson"]] = relationship("Lesson", back_populates="subject")  # Зв'язок з розкладом
    homeworks: Mapped[List["Homework"]] = relationship("Homework",
                                                       back_populates="subject")  # Зв'язок з домашніми завданнями

    # Зв'язок з користувачем-викладачем
    teacher_user: Mapped[Optional["User"]] = relationship("User")


class ScheduleTime(Base):
    """Таблиця часових рамок для пар (дзвінки)"""
    __tablename__ = "schedule_times"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair_number: Mapped[int] = mapped_column(Integer)  # 1-6
    start_time_1: Mapped[str] = mapped_column(String(10))  # 08:30
    end_time_1: Mapped[str] = mapped_column(String(10))  # 09:15
    break_start: Mapped[str] = mapped_column(String(10))  # 09:15
    break_end: Mapped[str] = mapped_column(String(10))  # 09:25
    start_time_2: Mapped[str] = mapped_column(String(10))  # 09:25
    end_time_2: Mapped[str] = mapped_column(String(10))  # 10:10
    is_big_break: Mapped[bool] = mapped_column(Boolean, default=False)


class WeekType(Base):
    """Таблиця для зберігання поточного типу тижня"""
    __tablename__ = "week_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))  # 'green' або 'red'
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class Lesson(Base):
    """Зв'язок предметів з часом та днями тижня"""
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    day_of_week: Mapped[int] = mapped_column(String(20))  # (Пн-Пт)
    lesson_number: Mapped[int] = mapped_column(Integer)  # Номер пари
    week_type: Mapped[str] = mapped_column(String(20))  # 'green', 'red', 'common'
    lesson_type: Mapped[str] = mapped_column(String(50), nullable=True)

    subgroup: Mapped[str] = mapped_column(String(20), default="all", nullable=False)
    subject: Mapped["Subject"] = relationship("Subject", back_populates="lessons")


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    description: Mapped[str] = mapped_column(Text)
    task_link: Mapped[Optional[str]] = mapped_column(String(500))
    extra_link: Mapped[Optional[str]] = mapped_column(String(500))
    video_link: Mapped[Optional[str]] = mapped_column(String(500))
    photo_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    teacher_note: Mapped[Optional[str]] = mapped_column(Text)

    subject: Mapped["Subject"] = relationship("Subject", back_populates="homeworks")


class ScheduleChange(Base):
    """Зміни у розкладі на конкретні дати"""
    __tablename__ = "schedule_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_date: Mapped[date] = mapped_column(Date)  # Конкретна дата (2026-02-25)
    weekday: Mapped[int] = mapped_column(Integer)
    pair_number: Mapped[int] = mapped_column(Integer)  # Номер пари
    new_subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    #
    # # Додатково (опціонально, якщо типи пар на замінах змінюються)
    new_type: Mapped[str] = mapped_column(String, nullable=True)

    new_subject: Mapped["Subject"] = relationship("Subject")