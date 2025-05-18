from sqlalchemy.orm import Session
import models, schemas
from datetime import date, timedelta, time

def get_event(db: Session, event_id: str):
    return db.query(models.Event).filter(models.Event.id == event_id).first()

def get_events_by_month(db: Session, year: int, month: int):
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    return db.query(models.Event).filter(models.Event.event_date >= start_date, models.Event.event_date <= end_date).all()

def create_event(db: Session, event: schemas.EventCreate):
    db_event = models.Event(
        name=event.name,
        event_date=event.event_date,
        start_time=event.start_time,
        end_time=event.end_time
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def get_all_events(db: Session):
    return db.query(models.Event).all()

def expand_recurring_event_for_month(
    name: str,
    day_of_week_str: str,
    start_time: time,
    end_time: time,
    target_year: int,
    target_month: int
) -> list[schemas.EventCreate]:
    """指定された月の繰り返し予定を具体的な日付のイベントリストに展開する"""
    created_events = []
    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    target_day_of_week = day_map.get(day_of_week_str.lower())

    if target_day_of_week is None:
        return []

    current_date = date(target_year, target_month, 1)
    while current_date.month == target_month:
        if current_date.weekday() == target_day_of_week:
            created_events.append(schemas.EventCreate(
                name=name,
                event_date=current_date,
                start_time=start_time,
                end_time=end_time
            ))
        current_date += timedelta(days=1)
    return created_events


def delete_events_by_date_and_name(db: Session, event_date: date, name: str) -> int:
    """
    指定された日付と名前の全てのイベントを削除する。
    削除された行数を返す。
    """
    events_to_delete = db.query(models.Event).filter(
        models.Event.event_date == event_date,
        models.Event.name == name
    )
    deleted_count = events_to_delete.delete(synchronize_session=False)
    db.commit()
    return deleted_count