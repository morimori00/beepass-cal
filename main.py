from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime, date, time, timedelta
import pathlib
import logging # ロギングの追加
from pydantic import BaseModel # Bodyのスキーマ定義用
from schemas import EventCreate, EventResponse, EventDetailProcessed 
import crud, models, schemas, gemini
from database import SessionLocal, engine, get_db

# ロガーの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = pathlib.Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "frontend")

# --- 削除リクエスト用のスキーマ ---
class DeleteEventPayload(BaseModel):
    event_date: date
    name: str
# --- ここまで ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
@app.post("/schedule/", response_model=List[EventResponse])
async def create_schedule_entry(
    name: str = Form(...),
    schedule_text: Optional[str] = Form(None),
    images: Optional[List[UploadFile]] = File(None), 
    target_year: int = Form(...),      # フロントエンドから受け取る年
    target_month: int = Form(...),     # フロントエンドから受け取る月
    db: Session = Depends(get_db)
):
    image_data_list: List[bytes] = []
    image_mime_type_list: List[str] = []
    if images: # images が None でなく、リストが空でもない場合
        for image_file in images:
            if image_file.content_type is None or not image_file.content_type.startswith("image/"):
                # 1つでも不正なファイルがあればエラーとするか、スキップするかは要件による
                # ここではエラーとする
                raise HTTPException(status_code=400, detail=f"アップロードされたファイル '{image_file.filename}' は画像ではありません。")
            image_data_list.append(await image_file.read())
            image_mime_type_list.append(image_file.content_type)
            logger.info(f"Image uploaded: {image_file.filename}, type: {image_file.content_type}, size: {len(image_data_list[-1])} bytes")


    if not schedule_text and not image_data_list: # テキストも画像リストも空の場合
         raise HTTPException(status_code=400, detail="予定テキストまたは画像を1つ以上入力/選択してください。")

    # target_yearとtarget_monthのバリデーション (任意だが推奨)
    try:
        # 有効な日付か確認 (例: 2024年2月30日は無効)
        datetime(target_year, target_month, 1) # 月の初日でテスト
    except ValueError:
        raise HTTPException(status_code=400, detail="無効な対象年月が指定されました。")


    try:
        logger.info(f"Calling Gemini for user: {name} (target: {target_year}-{target_month})")
        gemini_processed_data = await gemini.process_schedule_input_with_gemini(
            name=name,
            schedule_text=schedule_text,
            image_data_list=image_data_list,         # 変更
            image_mime_type_list=image_mime_type_list # 変更
        )
    # ... (ValueError, RuntimeError, Exception handling as before)
    except ValueError as e:
        logger.error(f"ValueError from Gemini processing: {str(e)}")
        raise HTTPException(status_code=400, detail=f"AI処理エラー: {str(e)}")
    except RuntimeError as e:
        logger.error(f"RuntimeError from Gemini API call: {str(e)}")
        raise HTTPException(status_code=503, detail=f"AIサービスとの通信に失敗しました: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during Gemini processing: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"予期せぬエラーが発生しました: {str(e)}")


    if not gemini_processed_data:
        logger.warning(f"Gemini returned no data for user {name}")
        raise HTTPException(status_code=400, detail="AIが予定情報を抽出できませんでした。")

    response_name = gemini_processed_data.get("name", name)
    processed_event_details: List[EventDetailProcessed] = gemini_processed_data.get("events", [])

    if not processed_event_details:
        logger.info(f"Gemini found no processable events for user {response_name}.")
        return []

    created_db_events = []
    # 繰り返し予定展開の基準日はフロントから渡された target_year, target_month を使用

    for event_detail in processed_event_details:
        if event_detail.event_date:
            event_to_create = EventCreate(
                name=response_name,
                event_date=event_detail.event_date,
                start_time=event_detail.start_time,
                end_time=event_detail.end_time
            )
            db_event = crud.create_event(db=db, event=event_to_create)
            created_db_events.append(db_event)
        elif event_detail.day_of_week and isinstance(event_detail.day_of_week, str):
            logger.info(f"Expanding recurring event for {response_name} on {event_detail.day_of_week} for month {target_year}-{target_month}")
            expanded_events = crud.expand_recurring_event_for_month(
                name=response_name,
                day_of_week_str=event_detail.day_of_week,
                start_time=event_detail.start_time,
                end_time=event_detail.end_time,
                target_year=target_year,      # ★ ここで受け取った年を使用
                target_month=target_month     # ★ ここで受け取った月を使用
            )
            for single_event_data in expanded_events:
                db_event = crud.create_event(db=db, event=single_event_data)
                created_db_events.append(db_event)
        else:
            logger.warning(f"イベントに日付または有効な曜日情報がないためスキップ: name={response_name}, start={event_detail.start_time}")
            continue

    if not created_db_events:
        logger.info(f"No events were ultimately created for user {response_name} after processing Gemini response.")
        raise HTTPException(status_code=400, detail="AIからの情報では登録できる有効な予定がありませんでした。")

    logger.info(f"Successfully created {len(created_db_events)} events for user {response_name}.")
    return created_db_events

# (他のエンドポイント /events/, /free_slots/ は変更なし)
@app.get("/events/", response_model=List[schemas.EventResponse])
def read_events_for_month(
    year: int = datetime.now().year,
    month: int = datetime.now().month,
    db: Session = Depends(get_db)
):
    events = crud.get_events_by_month(db, year=year, month=month)
    return events

@app.get("/free_slots/")
def get_free_slots(
    year: int = Query(default_factory=lambda: datetime.now().year, description="対象年"),
    month: int = Query(default_factory=lambda: datetime.now().month, description="対象月"),
    members: Optional[List[str]] = Query(None, description="空き時間を検索するメンバーのリスト (指定しない場合は全イベント参加者)"), # ★追加

    # day: Optional[int] = Query(None, description="対象日 (指定しない場合は月全体)"), # dayパラメータは一旦削除（月単位でのみ検索）
    duration_minutes: int = Query(60, description="空き時間とみなす最小持続時間 (分)"),
    work_start_time: str = Query("07:00", description="検索対象の業務開始時刻 (HH:MM)"),
    work_end_time: str = Query("22:00", description="検索対象の業務終了時刻 (HH:MM)"),
    db: Session = Depends(get_db)
) -> Dict[str, List[Dict[str, str]]]: # 返り値の型アノテーションを明確化
    """
    指定された月の中で、全メンバーが共通して空いている時間帯を検索する。
    返り値は {"YYYY-MM-DD": [{"start": "HH:MM", "end": "HH:MM"}, ...], ...} の形式。
    """
    logger.info(
        f"Searching for free slots in {year}-{month}, duration: {duration_minutes}min, "
        f"work hours: {work_start_time}-{work_end_time}"
    )

    # 対象となる日付リストを生成 (指定された月全体)
    target_dates: List[date] = []
    try:
        # 月の初日
        current_d = date(year, month, 1)
        # 月の最終日までループ
        while current_d.month == month:
            target_dates.append(current_d)
            current_d += timedelta(days=1)
    except ValueError: # 無効な年月が指定された場合
        logger.error(f"Invalid year/month provided for free_slots: {year}-{month}")
        raise HTTPException(status_code=400, detail=f"無効な年月です: {year}-{month}")

    if not target_dates: # 通常は到達しないはず
        return {}

    # 指定された月の全イベントを取得
    all_events_this_month = crud.get_events_by_month(db, year=year, month=month)
    if not all_events_this_month:
        logger.info(f"No events found in {year}-{month}. All work hours are considered free.")
        # イベントがない場合、全業務時間が空きスロットとなる
        # ただし、メンバーが存在しないと「全員が空いている」とは言えないので、
        # まずはメンバーリストを取得する。
        # ここでは簡単のため、イベントがなければ空きスロットも空として返す。
        # 必要に応じて、メンバーリストを別途取得するロジックを追加。
        # return {} # または、全業務時間をスロットとして生成して返す


    # メンバーリストを作成
    target_members: List[str]
    if members: # フロントエンドからメンバーリストが指定された場合
        target_members = members
        # 指定されたメンバーが実際にイベントを持っているかはここでは問わない
        # (イベントがないメンバーは常に空いているとみなされる)
        if not target_members: # 空のリストが来た場合 (例: members=[])
             logger.info("Empty member list provided. No common free slots possible.")
             return {}
    else: # メンバーリストが指定されなかった場合 (従来の動作)
        if not all_events_this_month:
            logger.info(f"No events found in {year}-{month}. Cannot determine common free slots without specified members.")
            return {}
        target_members = list(set(event.name for event in all_events_this_month))
        if not target_members:
            logger.info(f"No members with events in {year}-{month} (and no specific members requested).")
            return {}


    logger.info(f"Found members for {year}-{month}: {members}")

    # 業務開始時刻と終了時刻をtimeオブジェクトに変換
    try:
        work_start_t = datetime.strptime(work_start_time, "%H:%M").time()
        work_end_t = datetime.strptime(work_end_time, "%H:%M").time()
        if work_start_t >= work_end_t:
            raise ValueError("業務開始時刻が終了時刻以降です。")
    except ValueError as e:
        logger.error(f"Invalid work_start_time or work_end_time: {e}")
        raise HTTPException(status_code=400, detail=f"無効な業務時間形式です: {e}")

    free_slots_by_date: Dict[str, List[Dict[str, str]]] = {}
    slot_duration = timedelta(minutes=duration_minutes)

    for target_date_obj in target_dates:
        daily_free_slots_for_all_members: List[Dict[str, str]] = []

        # その日のタイムスロットを生成 (例: 09:00, 09:30, 10:00, ...)
        current_slot_start_dt = datetime.combine(target_date_obj, work_start_t)
        work_end_dt_for_day = datetime.combine(target_date_obj, work_end_t)

        while current_slot_start_dt + slot_duration <= work_end_dt_for_day:
            current_slot_end_dt = current_slot_start_dt + slot_duration
            slot_is_free_for_all = True

            for member_name in target_members: # ★ 決定されたメンバーリストを使用
                member_is_busy_in_slot = False
                for event in all_events_this_month: # この月の全イベントから探す
                    if event.name == member_name and event.event_date == target_date_obj:
                        event_start_dt = datetime.combine(event.event_date, event.start_time)
                        event_end_dt = datetime.combine(event.event_date, event.end_time)
                        if max(current_slot_start_dt, event_start_dt) < min(current_slot_end_dt, event_end_dt):
                            member_is_busy_in_slot = True
                            break
                if member_is_busy_in_slot:
                    slot_is_free_for_all = False
                    break
            
            if slot_is_free_for_all:
                daily_free_slots_for_all_members.append({
                    "start": current_slot_start_dt.time().strftime("%H:%M"),
                    "end": current_slot_end_dt.time().strftime("%H:%M")
                })
            current_slot_start_dt = current_slot_end_dt

        if daily_free_slots_for_all_members:
            free_slots_by_date[target_date_obj.isoformat()] = daily_free_slots_for_all_members

    logger.info(f"Found free_slots_by_date: {free_slots_by_date}")
    return free_slots_by_date


# --- 新しい削除エンドポイント ---
@app.delete("/events/delete_by_date_name/")
async def delete_events_by_date_and_name(
    payload: DeleteEventPayload, # リクエストボディとして受け取る
    db: Session = Depends(get_db)
):
    try:
        deleted_count = crud.delete_events_by_date_and_name(
            db=db,
            event_date=payload.event_date,
            name=payload.name
        )
        if deleted_count > 0:
            return {"message": f"{payload.event_date} の {payload.name} さんの予定を {deleted_count} 件削除しました。"}
        else:
            return {"message": f"{payload.event_date} に {payload.name} さんの予定は見つかりませんでした。"}
    except Exception as e:
        logger.error(f"Error deleting events for {payload.name} on {payload.event_date}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"予定の削除中にエラーが発生しました: {str(e)}")
# --- ここまで ---

@app.get("/all_delete")
def delete_all_events(db: Session = Depends(get_db)):
    """全てのイベントを削除するエンドポイント"""
    all_events = crud.get_all_events(db)
    for event in all_events:
        db.delete(event)
    db.commit()
    return {"message": "All events deleted."}