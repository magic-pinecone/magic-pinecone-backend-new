import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.api.deps import get_db
from app.main import app
from app.models.course import College, Course, Department


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed test data
        college = College(college_id="collegeI0", college_name="文學院")
        dept = Department(department_id="dept1001", department_name="中文系", college_id="collegeI0")
        course = Course(
            serial_no=1001,
            class_no="112100-1",
            title="國文基本讀本",
            credit=3.0,
            password_card="OPTIONAL",
            teachers=["張教授"],
            class_times=["1-1", "1-2"],
            limit_cnt=50,
            admit_cnt=40,
            wait_cnt=0,
            course_type="REQUIRED",
            college_ids=["collegeI0"],
            department_ids=["dept1001"],
        )
        session.add(college)
        session.add(dept)
        session.add(course)
        session.commit()
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_db_override():
        return session

    app.dependency_overrides[get_db] = get_db_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_openapi(client: TestClient):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert "paths" in response.json()


def test_get_colleges(client: TestClient):
    response = client.get("/api/v1/courses/colleges")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["college_id"] == "collegeI0"
    assert data[0]["college_name"] == "文學院"


def test_get_departments(client: TestClient):
    response = client.get("/api/v1/courses/departments?college_id=collegeI0")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["department_id"] == "dept1001"
    assert data[0]["department_name"] == "中文系"


def test_search_courses(client: TestClient):
    response = client.get("/api/v1/courses?search=國文")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["serial_no"] == 1001
    assert data["items"][0]["title"] == "國文基本讀本"


def test_get_course_detail(client: TestClient):
    response = client.get("/api/v1/courses/1001")
    assert response.status_code == 200
    data = response.json()
    assert data["serial_no"] == 1001
    assert data["title"] == "國文基本讀本"


def test_get_course_not_found(client: TestClient):
    response = client.get("/api/v1/courses/99999")
    assert response.status_code == 404


def test_scraper_schedule_endpoints(client: TestClient):
    # GET schedule
    get_res = client.get("/api/v1/scraper/schedule")
    assert get_res.status_code == 200
    assert "interval_minutes" in get_res.json()

    # POST schedule
    post_res = client.post("/api/v1/scraper/schedule", json={"interval_minutes": 120})
    assert post_res.status_code == 200
    assert post_res.json()["interval_minutes"] == 120
