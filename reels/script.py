"""확정된 대본(.md, .txt)을 대본 JSON으로 바꾸고 검사한다.

지원 형식: '시간 | 화면 | 대사 | 화면 자막' 열을 가진 마크다운 표.
본문(캡션), 해시태그, 썸네일 문구는 제목 아래 코드 블록이나 해시태그 줄에서 읽는다.
"""

import re

TIME_RANGE = re.compile(r"(\d+)\s*~\s*(\d+)\s*초")
SEPARATOR = re.compile(r"^:?-{3,}:?$")
HASHTAG_LINE = re.compile(r"(#\S+\s*)+")


def _table_rows(lines: list[str]) -> list[dict]:
    header_at = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("|") and "시간" in line and "대사" in line),
        None,
    )
    if header_at is None:
        return []
    headers = [cell.strip() for cell in lines[header_at].strip().strip("|").split("|")]
    rows = []
    for line in lines[header_at + 1:]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(SEPARATOR.match(cell) for cell in cells if cell):
            continue  # |---|---| 구분선
        rows.append(dict(zip(headers, cells)))
    return rows


def _column(row: dict, prefix: str) -> str:
    key = next((k for k in row if k.startswith(prefix)), None)
    return row[key] if key else ""


def _block_after(lines: list[str], heading_keyword: str) -> str | None:
    """제목에 키워드가 있는 줄 아래에서 첫 번째 코드 블록의 내용을 가져온다."""
    start = next((i for i, line in enumerate(lines) if line.startswith("#") and heading_keyword in line), None)
    if start is None:
        return None
    fences = [i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("```")]
    if len(fences) < 2:
        return None
    return "\n".join(lines[fences[0] + 1:fences[1]]).strip()


def _hashtags(lines: list[str]) -> list[str]:
    for line in lines:
        if HASHTAG_LINE.fullmatch(line.strip()):
            return line.split()
    return []


def parse_script(text: str, reel_id: str) -> dict:
    lines = text.splitlines()
    rows = _table_rows(lines)
    if not rows:
        raise ValueError("대본 표를 찾지 못했습니다. '시간 | 화면 | 대사 | 화면 자막' 형식의 표가 필요합니다.")

    beats = []
    for number, row in enumerate(rows, start=1):
        time_cell = row.get("시간", "")
        match = TIME_RANGE.search(time_cell)
        if not match:
            raise ValueError(f"{number}번째 줄의 시간을 읽지 못했습니다: '{time_cell}'")
        caption = _column(row, "화면 자막").replace("<br>", " / ").strip()
        beats.append({
            "no": number,
            "target_start": int(match.group(1)),
            "target_end": int(match.group(2)),
            "visual": row.get("화면", "").strip(),
            "narration": row.get("대사", "").replace("**", "").strip(),
            "caption": None if not caption or caption.startswith("(자막 없음") else caption,
        })

    title = next((line[2:].strip() for line in lines if line.startswith("# ")), reel_id)
    thumbnail = _block_after(lines, "썸네일") or ""
    return {
        "id": reel_id,
        "title": title,
        "length_seconds": max(beat["target_end"] for beat in beats),
        "lines": beats,
        "caption_body": _block_after(lines, "본문") or "",
        "hashtags": _hashtags(lines),
        "thumbnail_texts": [line.strip() for line in thumbnail.splitlines() if line.strip()],
    }


def check_script(data: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    beats = data.get("lines", [])
    if not beats:
        errors.append("줄이 하나도 없습니다.")

    previous_end = None
    for beat in beats:
        no, start, end = beat["no"], beat["target_start"], beat["target_end"]
        if end <= start:
            errors.append(f"{no}번: 끝 시간({end}초)이 시작 시간({start}초)보다 빠릅니다.")
            continue
        if not beat["narration"]:
            errors.append(f"{no}번: 대사가 비어 있습니다.")
        if previous_end is not None and start != previous_end:
            warnings.append(f"{no}번: 앞 줄과 시간이 이어지지 않습니다 ({previous_end}초 → {start}초).")
        previous_end = end
    return errors, warnings
