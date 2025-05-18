import os
import base64
import json
from typing import Optional, List, Union, Dict, Any
from openai import OpenAI, APIError
from pydantic import ValidationError # ValidationErrorはPydanticモデルのパースに使う
import logging
from datetime import date, time, datetime as dt

# EventDetailProcessed を gemini.py からも参照できるようにする
# (実際には main.py で使うので、schemas からインポートする)
from schemas import GeminiResponseEvent as GeminiResponseSchema, EventDetailProcessed # 名前を変更
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

logger = logging.getLogger(__name__)

client = OpenAI(
    # api_key=OPENAI_API_KEY,
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/"
)
MODEL_NAME = "models/gemini-2.0-flash" # または適切なモデル
# MODEL_NAME = "gpt-4.1"
# MODEL_NAME = "models/gemini-2.5-pro-preview-05-06"

def image_to_base64_data_url(image_data: bytes, mime_type: str = "image/jpeg") -> str:
    base64_encoded_data = base64.b64encode(image_data).decode('utf-8')
    return f"data:{mime_type};base64,{base64_encoded_data}"

def _parse_time_str(time_str: Any) -> Optional[time]:
    if not isinstance(time_str, str):
        return None
    try:
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        return time(hour, minute, second)
    except (ValueError, IndexError, TypeError):
        logger.warning(f"無効な時間形式をスキップ: {time_str}")
        return None

def _parse_date_str(date_str: Any) -> Optional[date]:
    if not isinstance(date_str, str):
        return None
    try:
        return dt.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning(f"無効な日付形式をスキップ: {date_str}")
        return None

async def process_schedule_input_with_gemini(
    name: str,
    schedule_text: Optional[str] = None,
    image_data_list: Optional[List[bytes]] = None,
    image_mime_type_list: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]: # 返り値をDict[str, Any] (nameと処理済みevents) に変更
    """
    Gemini APIを呼び出し、レスポンスをパースして必要な情報を抽出する。
    Pydanticによる厳密なバリデーションは行わず、キー存在と基本的な型変換を試みる。
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        error_msg = "Gemini APIキーが設定されていません。"
        logger.error(error_msg)
        raise ValueError(error_msg)

    has_text = bool(schedule_text)
    has_images = bool(image_data_list and image_mime_type_list and len(image_data_list) > 0 and len(image_data_list) == len(image_mime_type_list))

    if not has_text and not has_images:
        raise ValueError("予定テキストまたは画像が提供されていません。")

    schedule_info_for_prompt_parts = []
    if has_text:
        schedule_info_for_prompt_parts.append(schedule_text)
    if has_images:
        schedule_info_for_prompt_parts.append(f"添付画像 ({len(image_data_list)}) を参照して予定を抽出してください。")

    prompt_messages_content: List[Union[str, Dict[str, Union[str, Dict[str,str]]]]] = []
    system_prompt = f"""
あなたの役割は、ユーザーから与えられた情報を元に、予定をJSON形式で出力することです。

出力JSON形式 (この形式に厳密に従ってください。前後に説明文やマークダウン記法（```json ... ```など）を一切含めないでください。純粋なJSONオブジェクトのみを出力してください。):
{{
  "name": "{name}",
  "events": [
    {{ "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM" }},
    {{ "day_of_week": "Monday", "start": "HH:MM", "end": "HH:MM" }}
  ]
}}
- 曜日ごとの予定は "day_of_week" フィールド (例: "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") を使用してください。
- 年は特に指定がない場合、2025年を想定してください。
- 時間は特に指定がない場合、「終日」の場合は、時間を0:00から23:59までに指定してください。
- 画像で時間割が提供されている場合は、"{{ "day_of_week": "Monday", "start": "HH:MM", "end": "HH:MM" }}"のフォーマットを使用し、各曜日の授業がある時間を画像から推測し、予定として追加してください。
- カレンダーの画像が提供されている場合は、"{{ "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM" }}"のフォーマットを使用し、画像から予定を推測してください。
- 日付や曜日の指定がない場合は、可能な範囲で内容から推測してください。不明な場合はその予定を含めないでください。
    """
    instruction_text = f"""
氏名: {name}
予定情報: {schedule_info_for_prompt_parts}
"""
    prompt_messages_content.append({"type": "text", "text": instruction_text})
    if has_images and image_data_list and image_mime_type_list: # 再度Noneチェック
        for i in range(len(image_data_list)):
            img_data = image_data_list[i]
            mime_type = image_mime_type_list[i]
            if img_data and mime_type:
                base64_image_url = image_to_base64_data_url(img_data, mime_type)
                prompt_messages_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": base64_image_url
                    }
                })
            else:
                logger.warning(f"Skipping invalid image data or mime_type at index {i}")

    api_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_messages_content}
    ]
    try:
        logger.info(f"Sending request to Gemini (model: {MODEL_NAME})...")
        chat_completion = client.chat.completions.create(
            messages=api_messages, # type: ignore
            model=MODEL_NAME,
            temperature=0.8,
        )

        if not (chat_completion.choices and chat_completion.choices[0].message and
                chat_completion.choices[0].message.content):
            error_msg = "Gemini APIから空または無効な応答が返されました。"
            logger.error(error_msg)
            raise RuntimeError(error_msg) # API通信自体は成功したが中身がないケース

        raw_response_content = chat_completion.choices[0].message.content
        logger.info(f"Raw Gemini response content: {raw_response_content}")

        cleaned_response_content = raw_response_content.strip()
        if cleaned_response_content.startswith("```json"):
            cleaned_response_content = cleaned_response_content[7:]
        if cleaned_response_content.endswith("```"):
            cleaned_response_content = cleaned_response_content[:-3]
        cleaned_response_content = cleaned_response_content.strip()

        try:
            gemini_output_dict = json.loads(cleaned_response_content)
        except json.JSONDecodeError as e:
            error_msg = f"Gemini APIがJSON形式でない応答を返しました: {e}. Response: {cleaned_response_content[:200]}..."
            logger.error(error_msg)
            raise ValueError(error_msg) from e

        # GeminiResponseSchema で大枠(name, eventsキーの存在)だけ確認
        try:
            # Pydanticモデルを使って、nameとeventsキーの存在、eventsがリストであることを確認
            parsed_shell = GeminiResponseSchema.model_validate(gemini_output_dict)
            response_name = parsed_shell.name
            raw_events_list = parsed_shell.events # この時点では List[dict]
        except ValidationError as e:
            error_msg = f"Gemini APIの応答の基本構造が不正です (nameまたはeventsキーがない等): {e}. Response: {cleaned_response_content[:200]}..."
            logger.error(f"Pydantic shell validation error: \n{e.errors(include_url=False)}")
            raise ValueError(error_msg) from e

        processed_events: List[EventDetailProcessed] = []
        for event_dict in raw_events_list:
            if not isinstance(event_dict, dict):
                logger.warning(f"イベントリスト内の要素が辞書ではありません、スキップします: {type(event_dict)} - {str(event_dict)[:50]}")
                continue

            # 必須キー: start, end
            start_str = event_dict.get("start")
            end_str = event_dict.get("end")

            start_time_obj = _parse_time_str(start_str)
            end_time_obj = _parse_time_str(end_str)

            if not start_time_obj or not end_time_obj:
                logger.warning(f"イベントに必須の開始/終了時刻がないか、形式が不正です。スキップ: {event_dict}")
                continue # startかendがなければ予定として不完全なのでスキップ

            # オプショナルキー: date, day_of_week
            date_str = event_dict.get("date")
            day_of_week_str = event_dict.get("day_of_week") # stringのはず

            date_obj = _parse_date_str(date_str) if date_str else None
            
            # date と day_of_week の両方がある場合、date を優先する (あるいはプロンプトで制御)
            # ここでは、どちらかがあれば採用
            if not date_obj and (day_of_week_str is None or not isinstance(day_of_week_str, str)):
                # 日付も曜日もない、または曜日が文字列でない場合はスキップ (あるいはログのみ)
                # logger.warning(f"イベントに日付または曜日情報がありません: {event_dict}")
                # このケースを許容するかは要件次第。ここでは、どちらかがないと予定として不完全とみなす。
                # ただし、start/endがあれば、特定の日付/曜日に紐づかない「タスク」のような扱いも可能
                pass # ここでは許容する（日付や曜日がなくても時間帯だけのイベントとして登録される可能性）

            if day_of_week_str is not None and not isinstance(day_of_week_str, str):
                logger.warning(f"day_of_week が文字列ではありません、Noneとして扱います: {day_of_week_str}")
                day_of_week_str = None


            # どちらも設定されていない場合、DBのnot null制約に引っかかる可能性があるため、
            # main.py側で date か day_of_week がないと登録しないロジックが必要になる
            # ここではEventDetailProcessedにそのまま渡す
            processed_events.append(
                EventDetailProcessed(
                    event_date=date_obj,
                    day_of_week=day_of_week_str if isinstance(day_of_week_str, str) else None, # 文字列でなければNone
                    start_time=start_time_obj,
                    end_time=end_time_obj
                )
            )
        
        # 最終的なレスポンスは、名前と処理済みのイベントリスト
        return {"name": response_name, "events": processed_events}


    except APIError as e:
        error_msg = f"Gemini API呼び出しでエラー (APIError): {e.status_code} - {e.message}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Gemini API処理中に予期せぬエラー: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e