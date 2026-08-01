from sqlmodel import Session, create_engine, select

from app.core.config import settings

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))

def init_db(session: Session):
    # TODO: Ensure that which commands should be run here at init.