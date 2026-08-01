from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.models import College, Course, Department  # noqa: F401

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


def init_db(session: Session):
    SQLModel.metadata.create_all(engine)