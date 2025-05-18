from pydantic import BaseModel, field_validator
from typing import List, Optional, Any # Any をインポート
from datetime import date, time, datetime as dt

# EventDetailは、Geminiからの応答を柔軟に受け入れるようにする
# 型チェックは緩くし、後続処理でキーの存在と基本的な型を確認する
class EventDetailProcessed(BaseModel): # DB登録用に変換後の構造
    event_date: Optional[date] = None
    day_of_week: Optional[str] = None
    start_time: time
    end_time: time

class GeminiResponseEvent(BaseModel):
    name: str
    # eventsは辞書のリストとして受け取る。中身のバリデーションは後続処理で行う
    events: List[dict] # または List[Any] でも良いが、辞書であることを期待

# データベース登録用のスキーマは厳密な型を維持
class EventBase(BaseModel):
    name: str
    event_date: date
    start_time: time
    end_time: time

class EventCreate(EventBase):
    pass

class EventResponse(EventBase):
    id: str
    model_config = { # Pydantic V2
        "from_attributes": True
    }

class ScheduleInput(BaseModel):
    name: str
    schedule_text: Optional[str] = None