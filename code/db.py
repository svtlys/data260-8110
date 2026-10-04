import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "")
DATABASE_URL = f"mysql+pymysql://root:{DB_PASSWORD}@localhost/s8110_rel"

engine = create_engine(DATABASE_URL, echo=False)

db_session_basede26 = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = db_session_basede26()
    try:
        yield db
    finally:
        db.close()