from sqlalchemy import Column, String, Date, Time
from sqlalchemy.dialects.postgresql import UUID # UUIDはSQLiteではTEXTとして扱われる
import uuid
from database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True, nullable=False)
    event_date = Column(Date, nullable=False) # YYYY-MM-DD
    start_time = Column(Time, nullable=False) # HH:MM
    end_time = Column(Time, nullable=False)   # HH:MM