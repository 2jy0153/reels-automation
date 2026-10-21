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


def has_clips(item: dict) -> bool:
    return bool(item.get("clips")) or bool(item.get("clip"))


def draft_plan(timeline: list[dict], clips: dict[str, dict], needed: dict[int, int],
               existing: list[dict] | None = None) -> list[dict]:
    """clips: 파일 경로 → 태그 기록. needed: 문단 번호 → 필요한 영상 개수 (문장마다 1~3개).

    existing: 이미 정한 계획. 영상이 정해진 문단은 그대로 두고, 빈 문단만 태그로 채운다.
    태그가 없으면 빈 문단으로 두어, 나중에 수동으로 매칭할 수 있게 한다.
    같은 영상은 적게 쓰도록 점수에서 감점한다.
    """
    manual = {item["no"]: item for item in existing or [] if has_clips(item)}
    uses: dict[str, int] = {}
    plan = []
    for line in timeline:
        if line["no"] in manual:
            plan.append(manual[line["no"]])
            continue
        count = min(max(1, needed.get(line["no"], 1)), len(clips))
        chosen: list[str] = []
        for _ in range(count):
            candidates = [path for path in clips if path not in chosen]
            if not candidates:
                break
            best = max(candidates, key=lambda path: score(line["narration"], clips[path], uses.get(path, 0)))
            chosen.append(best)
            uses[best] = uses.get(best, 0) + 1
        if not chosen:
            plan.append(placeholder(line))
            continue
        plan.append({
            "no": line["no"],
            "clips": [{"clip": path, "in": None} for path in chosen],
            "note": f"태그로 고른 영상 {len(chosen)}개 (필요 {needed.get(line['no'], 1)}개)",
        })
    return plan
