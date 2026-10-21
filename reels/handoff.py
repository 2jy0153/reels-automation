"""컨펌된 기획 문서를 제작 단계로 넘기기 전에 확인한다.

넘어가는 조건 (하나라도 어기면 멈춘다)
1) 문서에 '상태: 컨펌' 줄이 있다. 기획 중인 문서는 '상태: 기획중'처럼 적는다.
2) 대본(대사·장면·화면 자막)에 빈칸이 없다. 빈칸은 '[ ]'(예: [ ]g)와
   아직 고르지 않은 선택지 '[A/B]'(예: [손잡이/숄더])다.
3) 문서에 체크하지 않은 할 일 '- [ ] ...'이 없다 ('채울 것' 목록).

확인을 통과하면 대본 JSON과 촬영 체크리스트를 만든다.
"""

import re

STATUS = re.compile(r"^\s*(?:>\s*)?\**상태\**\s*[:：]\s*(.+?)\s*$")
CONFIRMED = "컨펌"
BLANK = re.compile(r"\[\s*\](?!\()|\[[^\]\n]*/[^\]\n]*\](?!\()")  # [ ] 또는 [A/B], 링크 [글](주소)는 제외
TODO = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+?)\s*$")
FIELDS = {"narration": "대사", "visual": "장면", "caption": "화면 자막"}


def status(text: str) -> str | None:
    for line in text.splitlines():
        match = STATUS.match(line)
        if match:
            return match.group(1).strip("* ")
    return None


def problems(text: str, data: dict) -> list[str]:
    found = []
    value = status(text)
    if value is None:
        found.append("'상태: 컨펌' 줄이 없습니다. 컨펌한 문서에만 붙입니다.")
    elif CONFIRMED not in value:
        found.append(f"상태가 '{value}'입니다. 컨펌된 문서만 넘어갑니다.")
    for line in data["lines"]:
        for key, label in FIELDS.items():
            for blank in BLANK.findall(line.get(key) or ""):
                found.append(f"{line['no']}번 {label}에 빈칸 {blank}: {line[key][:40]}")
    for row in text.splitlines():
        todo = TODO.match(row)
        if todo:
            found.append(f"채울 것이 남아 있습니다: {todo.group(1)}")
    return found


def _time(seconds: int | float) -> str:
    return f"{seconds:g}"


def shot_checklist(data: dict) -> str:
    """대본의 장면 열로 촬영 체크리스트(마크다운)를 만든다."""
    out = [f"# 촬영 체크리스트 · {data['title']}", ""]
    for line in data["lines"]:
        visual = line.get("visual") or "(장면 설명 없음)"
        out.append(f"- [ ] {line['no']}. {_time(line['target_start'])}~{_time(line['target_end'])}초 · {visual}")
    out.append("")
    return "\n".join(out)
