from datetime import datetime, timezone
from typing import Any
from sqlmodel import Column, Field, JSON, SQLModel


class College(SQLModel, table=True):
    __tablename__ = "colleges"

    college_id: str = Field(primary_key=True)
    college_name: str


class Department(SQLModel, table=True):
    __tablename__ = "departments"

    department_id: str = Field(primary_key=True)
    department_name: str
    college_id: str = Field(foreign_key="colleges.college_id")


class Course(SQLModel, table=True):
    __tablename__ = "courses"

    serial_no: int = Field(primary_key=True)
    class_no: str
    title: str
    credit: float = 0.0
    password_card: str | None = None

    teachers: list[str] = Field(default=[], sa_column=Column(JSON))
    class_times: list[str] = Field(default=[], sa_column=Column(JSON))

    limit_cnt: int | None = None
    admit_cnt: int | None = 0
    wait_cnt: int | None = 0

    course_type: str | None = None

    college_ids: list[str] = Field(default=[], sa_column=Column(JSON))
    department_ids: list[str] = Field(default=[], sa_column=Column(JSON))

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
