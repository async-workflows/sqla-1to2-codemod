"""An already-modern SQLAlchemy 2.0 module: the codemod must leave it untouched."""

from sqlalchemy import String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)


def get_user(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def all_users(session: Session):
    return session.execute(select(User)).scalars().all()
