"""태그와 대본을 맞춰 편집 계획 초안(edit/plan.json)을 만든다.

점수 기준 (대략적인 초안이므로 검토가 필요하다)
- 문단 대사와 클립의 장면·키워드가 겹치는 두 글자 조각의 수
- 세로 영상이면 가산점 (릴스 기준)
- 이미 쓴 클립은 감점 → 같은 영상이 반복되는 것을 줄인다
같은 클립을 다시 쓰면 이전에 쓴 구간 뒤에서 이어 가도록 시작 지점(in)을 옮긴다.
"""

import re

ORIENTATION_BONUS = 1.0
REUSE_PENALTY = 2.0


def bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s", "", text)
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def clip_text(record: dict) -> str:
    return " ".join([record.get("scene", ""), record.get("shot", ""), " ".join(record.get("keywords", []))])


def score(narration: str, record: dict, uses: int) -> float:
    value = float(len(bigrams(narration) & bigrams(clip_text(record))))
    if "세로" in record.get("orientation", []):
        value += ORIENTATION_BONUS
    return value - REUSE_PENALTY * uses


def placeholder(line: dict) -> dict:
    return {"no": line["no"], "clip": None, "in": 0.0,
            "note": f"영상 필요: {line['narration'][:20]}"}


def draft_plan(timeline: list[dict], clips: dict[str, dict], durations: dict[str, float],
               existing: list[dict] | None = None) -> list[dict]:
    """clips: 파일 경로 → 태그 기록, durations: 파일 경로 → 길이(초).

    existing: 이미 정한 계획. 영상이 정해진 문단은 그대로 두고, 빈 문단만 태그로 채운다.
    태그가 없으면 빈 문단으로 두어, 나중에 수동으로 매칭할 수 있게 한다.
    """
    manual = {item["no"]: item for item in existing or [] if item.get("clip")}
    uses: dict[str, int] = {}
    used_until: dict[str, float] = {}
    plan = []
    for index, line in enumerate(timeline):
        if line["no"] in manual:
            plan.append(manual[line["no"]])
            continue
        if not clips:
            plan.append(placeholder(line))
            continue
        best_path, best_score = None, None
        for path, record in clips.items():
            value = score(line["narration"], record, uses.get(path, 0))
            if best_score is None or value > best_score:
                best_path, best_score = path, value
        if best_path is None:
            plan.append(placeholder(line))
            continue

        piece_length = (timeline[index + 1]["start"] if index + 1 < len(timeline) else line["end"]) - line["start"]
        start_at = used_until.get(best_path, 0.0)
        if start_at + piece_length > durations.get(best_path, 0.0):
            start_at = 0.0  # 영상 끝을 넘으면 처음부터 다시 쓴다
        used_until[best_path] = start_at + piece_length
        uses[best_path] = uses.get(best_path, 0) + 1
        plan.append({
            "no": line["no"],
            "clip": best_path,
            "in": round(start_at, 3),
            "note": f"점수 {best_score:.1f}, 같은 영상 {uses[best_path]}번째",
        })
    return plan
