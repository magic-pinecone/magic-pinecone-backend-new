from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.models.course import College, Course, Department

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/colleges", response_model=list[College])
def list_colleges(session: SessionDep) -> Any:
    """Retrieve all colleges."""
    colleges = session.exec(select(College)).all()
    return colleges


@router.get("/departments", response_model=list[Department])
def list_departments(
    session: SessionDep,
    college_id: str | None = Query(None, description="Filter by college ID"),
) -> Any:
    """Retrieve departments, optionally filtered by college_id."""
    statement = select(Department)
    if college_id:
        statement = statement.where(Department.college_id == college_id)
    departments = session.exec(statement).all()
    return departments


@router.get("", response_model=dict[str, Any])
def search_courses(
    session: SessionDep,
    department_id: str | None = Query(None, description="Filter by department ID"),
    college_id: str | None = Query(None, description="Filter by college ID"),
    course_type: str | None = Query(None, description="Filter by course type (REQUIRED/ELECTIVE)"),
    search: str | None = Query(None, description="Search keyword in course title"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    """Search and list courses with pagination and filtering."""
    statement = select(Course)

    if course_type:
        statement = statement.where(Course.course_type == course_type)

    if search:
        statement = statement.where(Course.title.contains(search))  # type: ignore

    # Fetch results
    courses = session.exec(statement).all()

    # Memory filter JSON array fields (department_ids, college_ids) if requested
    filtered_courses = []
    for c in courses:
        if department_id and department_id not in c.department_ids:
            continue
        if college_id and college_id not in c.college_ids:
            continue
        filtered_courses.append(c)

    total = len(filtered_courses)
    paginated = filtered_courses[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": paginated,
    }


@router.get("/{serial_no}", response_model=Course)
def get_course_detail(serial_no: int, session: SessionDep) -> Any:
    """Get single course details by serial_no."""
    course = session.get(Course, serial_no)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course
