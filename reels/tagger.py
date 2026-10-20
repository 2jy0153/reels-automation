"""Gemini로 영상 파일을 직접 보고 태그를 만든다.

파일명만 보내면 태그가 추측이 되므로, 영상을 File API로 업로드해 내용을 분석한다.
결과는 허용된 값만 통과시키고, 맞지 않으면 '미확인'으로 표시한다.
"""

import json
import os
import time
from pathlib import Path

BAG_TYPES = ["백팩", "숄더백", "크로스백", "토트백", "핸드백", "여행가방", "가방_미포함"]
PERSON_TAGS = ["사람_있음", "사람_없음"]
UNKNOWN = "미확인"

PROMPT = f"""이 영상은 가방 브랜드 릴스용 촬영 클립입니다. 영상 내용을 직접 보고 아래 항목을 JSON으로만 답하세요.

- bag_type: 화면에 주로 보이는 가방 형식. 다음 중 하나: {", ".join(BAG_TYPES)}. 가방이 안 보이면 "가방_미포함". 판단이 어려우면 "{UNKNOWN}".
- person: 화면에 사람이 보이면 "사람_있음", 없으면 "사람_없음".
- shot: 촬영 방식을 한 단어로 (예: 제품_클로즈업, 착용, 손동작, 풍경, 이동).
- scene: 장면 설명을 한 문장으로.
- keywords: 검색에 쓸 짧은 한국어 키워드 배열 (최대 6개).
- confidence: bag_type 판단의 확신도 0~1 숫자.

추측하지 말고 화면에서 확인되는 것만 적으세요."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "bag_type": {"type": "STRING"},
        "person": {"type": "STRING"},
        "shot": {"type": "STRING"},
        "scene": {"type": "STRING"},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["bag_type", "person", "shot", "scene", "keywords", "confidence"],
}


def validate_tags(raw: dict) -> dict:
    """허용되지 않은 값은 '미확인'으로 바꾸고, needs_review로 표시한다."""
    bag = raw.get("bag_type")
    person = raw.get("person")
    needs_review = False

    if bag not in BAG_TYPES:
        bag = UNKNOWN
        needs_review = True
    if person not in PERSON_TAGS:
        person = UNKNOWN
        needs_review = True

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        confidence = 0.0
        needs_review = True
    if confidence < 0.6:
        needs_review = True

    keywords = [k for k in raw.get("keywords", []) if isinstance(k, str)][:6]

    return {
        "bag_type": bag,
        "person": person,
        "shot": str(raw.get("shot", UNKNOWN)),
        "scene": str(raw.get("scene", "")),
        "keywords": keywords,
        "confidence": float(confidence),
        "needs_review": needs_review,
    }


def is_quota_error(error: Exception) -> bool:
    """무료 한도나 크레딧을 다 쓴 오류인지 확인한다. 이 경우 나머지 영상도 실패할 것이므로 멈춘다."""
    if getattr(error, "code", None) == 429:
        return True
    text = str(error).lower()
    return "resource_exhausted" in text or "quota" in text or "rate limit" in text


def check_model(model: str, api_key_env: str = "GEMINI_API_KEY") -> str:
    """영상 분석 전에 모델 이름이 동작하는지 짧은 텍스트 호출로 확인한다."""
    from google import genai

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"환경 변수 {api_key_env}가 없습니다.")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents="한 단어로만 답하세요: 안녕")
    return response.text.strip()


def analyze_video(path: Path, model: str, api_key_env: str = "GEMINI_API_KEY") -> dict:
    """영상을 업로드하고 분석한 뒤 업로드 파일을 지운다."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"환경 변수 {api_key_env}가 없습니다.")

    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=str(path))
    try:
        # 업로드 직후에는 PROCESSING 상태이므로 ACTIVE가 될 때까지 기다린다.
        while uploaded.state.name == "PROCESSING":
            time.sleep(5)
            uploaded = client.files.get(name=uploaded.name)
        if uploaded.state.name != "ACTIVE":
            raise RuntimeError(f"업로드 처리 실패: {uploaded.state.name}")

        response = client.models.generate_content(
            model=model,
            contents=[uploaded, PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
        raw = json.loads(response.text)
    finally:
        client.files.delete(name=uploaded.name)

    return validate_tags(raw)
