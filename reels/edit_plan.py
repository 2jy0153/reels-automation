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


def draft_plan(timeline: list[dict], clips: dict[str, dict], durations: dict[str, float]) -> list[dict]:
    """clips: 파일 경로 → 태그 기록, durations: 파일 경로 → 길이(초)."""
    uses: dict[str, int] = {}
    used_until: dict[str, float] = {}
    plan = []
    for index, line in enumerate(timeline):
        best_path, best_score = None, None
        for path, record in clips.items():
            value = score(line["narration"], record, uses.get(path, 0))
            if best_score is None or value > best_score:
                best_path, best_score = path, value
        if best_path is None:
            raise ValueError("태깅된 영상이 없어 편집 계획을 만들 수 없습니다.")

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
