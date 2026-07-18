"""A small, realistic legacy SQLAlchemy 1.x module used as a codemod fixture."""

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)


def get_user(session: Session, user_id: int) -> User:
    return session.query(User).get(user_id)


def all_users(session: Session):
    return session.query(User).all()


def active_users(session: Session):
    return session.query(User).filter(User.name != None).all()


def raw_update(engine) -> None:
    engine.execute("UPDATE users SET name = 'x'")
