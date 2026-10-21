"""확정된 대본을 대본 JSON으로 바꾸고 검사한다.

두 가지 형식을 읽는다.
1) 표 형식: '시간 | 화면 | 대사 | 화면 자막' 열이 있는 마크다운 표
2) 일반 텍스트 (.txt, .md):
   - 시간 표시가 있으면 그대로 쓴다. 예: "0~3초 나레이션 내용", "[0~3] 내용"
   - 시간 표시가 없으면 문단 하나를 한 줄로 보고, 글자 수로 예상 시간(초당 6자)을 잡는다.
   - "자막:", "화면:", "대사:" 줄이 있으면 각각 자막, 화면, 대사로 쓴다.
   - "본문", "썸네일", "해시태그" 섹션을 인식한다.
"""

import re

TIME_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)\s*초")
SEPARATOR = re.compile(r"^:?-{3,}:?$")
HASHTAG_LINE = re.compile(r"(#\S+\s*)+")
PLAIN_TIME = re.compile(r"^\s*\[?\s*(\d{1,3})\s*[~\-–]\s*(\d{1,3})\s*(?:초|s)?\s*\]?\s*[:：]?\s*(.*)$")
HORIZONTAL_RULE = re.compile(r"-{3,}|\*{3,}|_{3,}")
SECTION = re.compile(r"^\s*#*\s*(본문|캡션|썸네일|해시태그)\s*[:：]?\s*$")
CAPTION_LABEL = re.compile(r"^\s*(?:화면\s*)?자막\s*[:：]\s*(.*)$")
VISUAL_LABEL = re.compile(r"^\s*화면\s*[:：]\s*(.*)$")
NARRATION_LABEL = re.compile(r"^\s*대사\s*[:：]\s*(.*)$")
CHARS_PER_SECOND = 6  # 일반 텍스트에 시간 표시가 없을 때 쓰는 예상 말 속도


def parse_script(text: str, reel_id: str, table: int | None = None) -> dict:
    """table: 대본 표가 여러 개(A안/B안 등)일 때 몇 번째 표를 쓸지 (1부터)."""
    lines = text.splitlines()
    rows = _table_rows(lines, table)
    if rows:
        return _from_table(lines, rows, reel_id)
    return _from_plain(lines, reel_id)


# ---------- 표 형식 ----------

def script_tables(lines: list[str]) -> list[int]:
    """'시간'과 '대사' 열이 있는 표의 머리줄 위치들."""
    return [i for i, line in enumerate(lines) if line.strip().startswith("|") and "시간" in line and "대사" in line]


def _table_rows(lines: list[str], table: int | None = None) -> list[dict]:
    headers_at = script_tables(lines)
    if not headers_at:
        return []
    if table is None and len(headers_at) > 1:
        raise ValueError(f"대본 표가 {len(headers_at)}개 있습니다. 컨펌한 표 번호를 --table로 정해 주세요 (1~{len(headers_at)}).")
    if table is not None and not 1 <= table <= len(headers_at):
        raise ValueError(f"대본 표는 {len(headers_at)}개입니다. --table {table}은 없습니다.")
    header_at = headers_at[(table or 1) - 1]
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


def _seconds(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def _visual(row: dict) -> str:
    # 예전 대본은 '화면', v3 대본은 '장면' 열을 쓴다.
    if "화면" in row:
        return row["화면"]
    return _column(row, "장면")


def _narration(row: dict) -> str:
    # '자막 (= 목소리를 넣는다면 대사)'처럼 이름에 '대사'가 들어간 열도 대사로 읽는다.
    if "대사" in row:
        return row["대사"]
    key = next((k for k in row if "대사" in k), None)
    return row[key] if key else ""


def _column(row: dict, prefix: str) -> str:
    key = next((k for k in row if k.startswith(prefix)), None)
    return row[key] if key else ""


def _from_table(lines: list[str], rows: list[dict], reel_id: str) -> dict:
    beats = []
    for number, row in enumerate(rows, start=1):
        time_cell = row.get("시간", "")
        match = TIME_RANGE.search(time_cell)
        if not match:
            raise ValueError(f"{number}번째 줄의 시간을 읽지 못했습니다: '{time_cell}'")
        caption = _column(row, "화면 자막").replace("<br>", " / ").strip()
        beats.append({
            "no": number,
            "target_start": _seconds(match.group(1)),
            "target_end": _seconds(match.group(2)),
            "visual": _visual(row).replace("**", "").strip(),
            "narration": _narration(row).replace("**", "").strip(),
            "caption": None if not caption or caption.startswith("(자막 없음") else caption,
        })
    return _build(reel_id, lines, beats, timing_estimated=False)


# ---------- 일반 텍스트 ----------

def _from_plain(lines: list[str], reel_id: str) -> dict:
    body, sections = _split_sections(lines)
    body = _without_title(body)
    hashtags = []
    content = []
    for line in body:
        if HORIZONTAL_RULE.fullmatch(line.strip()):
            continue  # --- 같은 구분선은 대사가 아니다
        if HASHTAG_LINE.fullmatch(line.strip()) and not line.strip().startswith("# "):
            hashtags.extend(line.split())
        else:
            content.append(line)

    has_markers = any(PLAIN_TIME.match(line) for line in content)
    beats = _plain_beats_with_markers(content) if has_markers else _plain_beats_by_paragraph(content)
    if not beats:
        raise ValueError("대사를 찾지 못했습니다. 문장이나 '0~3초 대사' 형식의 줄이 필요합니다.")

    data = _build(reel_id, lines, beats, timing_estimated=not has_markers)
    data["hashtags"] = hashtags or data["hashtags"]
    data["caption_body"] = "\n".join(sections.get("본문", [])).strip() or data["caption_body"]
    thumbnail = [
        line.strip() for line in sections.get("썸네일", [])
        if line.strip() and not HASHTAG_LINE.fullmatch(line.strip())
    ]
    data["thumbnail_texts"] = thumbnail or data["thumbnail_texts"]
    return data


def _without_title(lines: list[str]) -> list[str]:
    """맨 앞의 '# 제목' 줄은 대사가 아니므로 뺀다."""
    for index, line in enumerate(lines):
        if line.strip():
            return lines[:index] + lines[index + 1:] if line.strip().startswith("# ") else lines
    return lines


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    body: list[str] = []
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        header = SECTION.match(line)
        if header:
            current = header.group(1)
            sections.setdefault(current, [])
            continue
        if current is None:
            body.append(line)
        else:
            sections[current].append(line)
    return body, sections


def _plain_beats_with_markers(content: list[str]) -> list[dict]:
    beats: list[dict] = []
    for line in content:
        marker = PLAIN_TIME.match(line)
        if marker and marker.group(1).isdigit() and marker.group(2).isdigit():
            beats.append({
                "no": len(beats) + 1,
                "target_start": int(marker.group(1)),
                "target_end": int(marker.group(2)),
                "visual": "",
                "narration": marker.group(3).strip(),
                "caption": None,
            })
            continue
        if not line.strip():
            continue
        if not beats:
            raise ValueError(f"첫 시간 표시보다 앞에 내용이 있습니다: '{line.strip()[:30]}'")
        _apply_label(beats[-1], line.strip())
    for beat in beats:
        if not beat["narration"]:
            raise ValueError(f"{beat['no']}번 줄에 대사가 없습니다.")
    return beats


def _plain_beats_by_paragraph(content: list[str]) -> list[dict]:
    paragraphs: list[list[str]] = []
    for line in content:
        if not line.strip():
            if paragraphs and paragraphs[-1]:
                paragraphs.append([])
            continue
        if not paragraphs or not paragraphs[-1]:
            paragraphs.append([])
        paragraphs[-1].append(line.strip())
    paragraphs = [p for p in paragraphs if p]

    beats: list[dict] = []
    cursor = 0
    for paragraph in paragraphs:
        beat = {"no": len(beats) + 1, "target_start": cursor, "target_end": cursor,
                "visual": "", "narration": "", "caption": None}
        for line in paragraph:
            _apply_label(beat, line)
        if not beat["narration"]:
            continue
        seconds = max(1, round(len(re.sub(r"\s", "", beat["narration"])) / CHARS_PER_SECOND))
        beat["target_end"] = cursor + seconds
        cursor = beat["target_end"]
        beats.append(beat)
    return beats


def _apply_label(beat: dict, line: str) -> None:
    """라벨이 있는 줄은 해당 칸에, 없는 줄은 대사에 이어 붙인다."""
    caption = CAPTION_LABEL.match(line)
    visual = VISUAL_LABEL.match(line)
    narration = NARRATION_LABEL.match(line)
    if caption:
        beat["caption"] = caption.group(1).strip() or None
    elif visual:
        beat["visual"] = visual.group(1).strip()
    elif narration:
        beat["narration"] = _join(beat["narration"], narration.group(1).strip())
    else:
        beat["narration"] = _join(beat["narration"], line)


def _join(current: str, addition: str) -> str:
    return f"{current} {addition}".strip() if current else addition


# ---------- 공통 ----------

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


def _build(reel_id: str, lines: list[str], beats: list[dict], timing_estimated: bool) -> dict:
    title = next((line.lstrip("#").strip() for line in lines if line.strip()), reel_id)
    thumbnail = _block_after(lines, "썸네일") or ""
    return {
        "id": reel_id,
        "title": title,
        "timing_estimated": timing_estimated,
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
    if data.get("timing_estimated"):
        warnings.append("시간 표시가 없어 글자 수로 예상한 시간입니다. 음성을 만든 뒤 실제 길이로 확인하세요.")
    return errors, warnings
