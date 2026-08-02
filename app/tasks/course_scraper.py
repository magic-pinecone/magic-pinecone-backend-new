import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import bs4
import httpx
from sqlmodel import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.celery_app import celery_app
from app.core.db import engine
from app.models.course import College, Course, Department

logger = logging.getLogger(__name__)

BASE_URL = "https://cis.ncu.edu.tw/Course/main"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def deflate_class_time(class_time_str: str) -> list[str]:
    """Convert raw class time string like '36,45,46' to ['3-6', '4-5', '4-6']."""
    if not class_time_str:
        return []
    result = []
    for item in class_time_str.split(","):
        item = item.strip()
        if len(item) == 2:
            result.append(f"{item[0]}-{item[1]}")
        elif item:
            result.append(item)
    return result


def normalize_course_type(raw_type: str) -> str:
    if "必" in raw_type:
        return "REQUIRED"
    if "選" in raw_type:
        return "ELECTIVE"
    return raw_type.strip()


class NCUCourseFetcher:
    """Async engine for fetching NCU course data with high concurrency & resilience."""

    def __init__(self, concurrency_limit: int = 10):
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(
        self, client: httpx.AsyncClient, url: str, params: dict | None = None
    ) -> httpx.Response:
        resp = await client.get(
            url, params=params, headers=HEADERS, follow_redirects=True, timeout=15.0
        )
        resp.raise_for_status()
        return resp

    async def fetch_colleges_with_departments(
        self, client: httpx.AsyncClient
    ) -> tuple[list[dict], list[dict]]:
        """Scrape colleges and departments list from byUnion page."""
        url = f"{BASE_URL}/query/byUnion"
        resp = await self._get(client, url)
        soup = bs4.BeautifulSoup(resp.content, "html.parser")

        colleges = []
        departments = []

        by_union = soup.find(id="byUnion_table")
        if not by_union:
            logger.warning("byUnion_table element not found on page.")
            return colleges, departments

        sub_tables = by_union.find_all("table")
        for i, table in enumerate(sub_tables):
            college_id = f"collegeI{i}"
            th = table.find("th")
            college_name = th.text.strip() if th else f"College {i}"

            colleges.append({"college_id": college_id, "college_name": college_name})

            anchors = table.find_all("a")
            for anchor in anchors:
                href = anchor.get("href", "")
                if "dept=" not in href:
                    continue
                dept_id = href.split("dept=")[-1].strip()
                dept_name = re.sub(r"\(\d+\)$", "", anchor.text.strip())

                if dept_id:
                    departments.append(
                        {
                            "department_id": dept_id,
                            "department_name": dept_name,
                            "college_id": college_id,
                        }
                    )

        return colleges, departments

    async def fetch_course_bases(
        self, client: httpx.AsyncClient, department_id: str, college_id: str
    ) -> list[dict]:
        """Fetch course bases XML for a specific department."""
        async with self.semaphore:
            url = f"{BASE_URL}/support/course.xml"
            try:
                resp = await self._get(client, url, params={"id": department_id})
                root = ET.fromstring(resp.content)
            except Exception as exc:
                logger.error(
                    f"Error fetching course bases for dept {department_id}: {exc}"
                )
                return []

            courses = []
            for course_elem in root.findall(".//Course"):
                attr = course_elem.attrib
                serial_no_str = attr.get("SerialNo", "")
                if not serial_no_str.isdigit():
                    continue

                serial_no = int(serial_no_str)
                raw_class_no = attr.get("ClassNo", "")
                class_no = (
                    f"{raw_class_no[:6]}-{raw_class_no[6:]}"
                    if len(raw_class_no) >= 6
                    else raw_class_no
                )

                teachers = [
                    t.strip() for t in attr.get("Teacher", "").split(",") if t.strip()
                ]
                class_times = deflate_class_time(attr.get("ClassTime", ""))

                limit_cnt = (
                    int(attr["limitCnt"])
                    if attr.get("limitCnt", "").isdigit()
                    else None
                )
                admit_cnt = (
                    int(attr["admitCnt"]) if attr.get("admitCnt", "").isdigit() else 0
                )
                wait_cnt = (
                    int(attr["waitCnt"]) if attr.get("waitCnt", "").isdigit() else 0
                )

                credit = float(attr.get("credit", 0.0))

                courses.append(
                    {
                        "serial_no": serial_no,
                        "class_no": class_no,
                        "title": attr.get("Title", ""),
                        "credit": credit,
                        "password_card": attr.get("passwordCard", ""),
                        "teachers": teachers,
                        "class_times": class_times,
                        "limit_cnt": limit_cnt,
                        "admit_cnt": admit_cnt,
                        "wait_cnt": wait_cnt,
                        "college_id": college_id,
                        "department_id": department_id,
                    }
                )

            return courses

    async def fetch_all_course_extras(
        self, client: httpx.AsyncClient
    ) -> dict[int, str]:
        """Fetch course types (REQUIRED/ELECTIVE) across paginated byKeywords pages."""
        url = f"{BASE_URL}/query/byKeywords"
        extras: dict[int, str] = {}
        page_no = 1

        while True:
            try:
                resp = await self._get(
                    client, url, params={"d-49489-p": page_no, "query": "true"}
                )
            except Exception as exc:
                logger.error(f"Error fetching course extras page {page_no}: {exc}")
                break

            soup = bs4.BeautifulSoup(resp.content, "html.parser")
            rows = soup.select("#item tbody tr")
            if not rows:
                break

            for row in rows:
                tds = row.find_all("td")
                if len(tds) < 6:
                    continue

                td0_str = str(tds[0])
                serial_part = td0_str.split("<br")[0].split(">")[-1].strip()
                if serial_part.isdigit():
                    serial_no = int(serial_part)
                    c_type = normalize_course_type(tds[5].text)
                    extras[serial_no] = c_type

            # Check next page link
            next_page_elem = soup.select_one(".pagelinks > :last-child")
            if not next_page_elem or next_page_elem.name != "a":
                break

            page_no += 1

        return extras

    async def fetch_all_data(self) -> dict[str, Any]:
        """Orchestrate full async data fetching."""
        async with httpx.AsyncClient() as client:
            logger.info("Fetching colleges and departments...")
            colleges, departments = await self.fetch_colleges_with_departments(client)
            logger.info(
                f"Found {len(colleges)} colleges and {len(departments)} departments."
            )

            # Concurrently fetch XMLs for all departments
            tasks = [
                self.fetch_course_bases(
                    client, dept["department_id"], dept["college_id"]
                )
                for dept in departments
            ]
            dept_course_lists = await asyncio.gather(*tasks)

            # Fetch course extras (REQUIRED / ELECTIVE)
            logger.info("Fetching course extras...")
            course_extras = await self.fetch_all_course_extras(client)

            # Aggregate course bases and extras by serial_no
            course_map: dict[int, dict] = {}
            for course_list in dept_course_lists:
                for cb in course_list:
                    s_no = cb["serial_no"]
                    if s_no not in course_map:
                        course_map[s_no] = {
                            "serial_no": cb["serial_no"],
                            "class_no": cb["class_no"],
                            "title": cb["title"],
                            "credit": cb["credit"],
                            "password_card": cb["password_card"],
                            "teachers": cb["teachers"],
                            "class_times": cb["class_times"],
                            "limit_cnt": cb["limit_cnt"],
                            "admit_cnt": cb["admit_cnt"],
                            "wait_cnt": cb["wait_cnt"],
                            "course_type": course_extras.get(s_no, "UNKNOWN"),
                            "college_ids": {cb["college_id"]},
                            "department_ids": {cb["department_id"]},
                        }
                    else:
                        course_map[s_no]["college_ids"].add(cb["college_id"])
                        course_map[s_no]["department_ids"].add(cb["department_id"])

            courses = [
                {
                    **item,
                    "college_ids": list(item["college_ids"]),
                    "department_ids": list(item["department_ids"]),
                }
                for item in course_map.values()
            ]

            return {
                "colleges": colleges,
                "departments": departments,
                "courses": courses,
            }


def _update_task_progress(task: Any, state: str, meta: dict):
    if hasattr(task, "request") and task.request and task.request.id:
        try:
            task.update_state(state=state, meta=meta)
        except Exception:
            pass


@celery_app.task(bind=True, name="tasks.course_scraper.scrape_ncu_courses")
def scrape_ncu_courses(self: Any, save_to_db: bool = True) -> dict[str, Any]:
    """Celery task to trigger NCU course scraping and update database."""
    logger.info("Starting NCU course scraping Celery worker task...")
    _update_task_progress(
        self, state="PROGRESS", meta={"status": "Fetching live course data from NCU..."}
    )

    fetcher = NCUCourseFetcher(concurrency_limit=10)
    data = asyncio.run(fetcher.fetch_all_data())

    colleges = data["colleges"]
    departments = data["departments"]
    courses = data["courses"]

    logger.info(
        f"Fetched {len(colleges)} colleges, {len(departments)} departments, and {len(courses)} courses."
    )

    if save_to_db:
        _update_task_progress(
            self, state="PROGRESS", meta={"status": "Updating database..."}
        )
        now = datetime.now(UTC)

        with Session(engine) as session:
            # 1. UPSERT Colleges
            for col in colleges:
                existing_col = session.get(College, col["college_id"])
                if existing_col:
                    existing_col.college_name = col["college_name"]
                else:
                    session.add(College(**col))

            # 2. UPSERT Departments
            for dept in departments:
                existing_dept = session.get(Department, dept["department_id"])
                if existing_dept:
                    existing_dept.department_name = dept["department_name"]
                    existing_dept.college_id = dept["college_id"]
                else:
                    session.add(Department(**dept))

            # 3. UPSERT Courses
            for crs_data in courses:
                existing_crs = session.get(Course, crs_data["serial_no"])
                if existing_crs:
                    existing_crs.class_no = crs_data["class_no"]
                    existing_crs.title = crs_data["title"]
                    existing_crs.credit = crs_data["credit"]
                    existing_crs.password_card = crs_data["password_card"]
                    existing_crs.teachers = crs_data["teachers"]
                    existing_crs.class_times = crs_data["class_times"]
                    existing_crs.limit_cnt = crs_data["limit_cnt"]
                    existing_crs.admit_cnt = crs_data["admit_cnt"]
                    existing_crs.wait_cnt = crs_data["wait_cnt"]
                    existing_crs.course_type = crs_data["course_type"]
                    existing_crs.college_ids = crs_data["college_ids"]
                    existing_crs.department_ids = crs_data["department_ids"]
                    existing_crs.updated_at = now
                else:
                    session.add(Course(**crs_data, updated_at=now))

            session.commit()
            logger.info("Database successfully updated with scraped NCU course data.")

    return {
        "status": "SUCCESS",
        "college_count": len(colleges),
        "department_count": len(departments),
        "course_count": len(courses),
    }
