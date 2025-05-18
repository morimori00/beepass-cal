from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///../scheduler.db" # プロジェクトルートからの相対パス

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} # SQLiteはシングルスレッドアクセスが基本
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()