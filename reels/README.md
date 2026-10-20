# 릴스 자동화

가방 브랜드 릴스를 만드는 자동화입니다. 기획과 대본 확정은 사람이 하고, 그다음 단계를 자동화합니다.
명령은 모두 Claude가 실행합니다. 사용자는 확인하고 "시작해"라고 말하면 됩니다.

## 폴더 구조 (SSD 안)

```
SOURCE_LIBRARY/
  INBOX/                     새 영상을 넣는 곳 (정리되면 비워짐)
  FOOTAGE/YYYY-MM-DD/        원본 보관. 날짜별, 수정·삭제 금지
  PROXY/YYYY-MM-DD/          분석·편집용 저용량 사본 (원본과 같은 이름)
  DUPLICATES/                중복으로 빠진 파일. 확인 후 직접 지움
  CLIP_INDEX/                클립 정보, 수집 기록(ingest_log.json)
  REELS/<릴스 ID>/           릴스 1편 = 폴더 1개
      script/                원본 대본, 대본 JSON
      voice/                 문장별 나레이션 mp3
      subtitles/             자막(SRT)
      graded/                색 보정본
      project/               Premiere 프로젝트
      export/                완성본
      thumbnail/             썸네일
  LIBRARY/PRODUCT/           기존 자료. 이 자동화는 건드리지 않음
```

원본(FOOTAGE)과 작업 폴더(REELS)를 나눈 이유: 원본은 한 번 정해지면 계속 참조만 하고, 편집 작업은 릴스마다 폴더를 따로 써야 나중에 찾기 쉽습니다. 영상 실무에서 흔히 쓰는 방식입니다.

## 파일 이름 규칙

`YYYYMMDD_나머지` 형식입니다. 시분초는 넣지 않습니다.

- 원래 이름에 촬영일(YYYYMMDD)이 있으면 그 날짜는 빼고, 맨 앞에 한 번만 붙입니다.
  - `IMG_20260904_150352.mp4` → `20260904_IMG_150352.mp4`
  - `20260904_150352.mp4` → `20260904_150352.mp4`
- 이름에 날짜가 없으면 파일 수정일을 맨 앞에 붙입니다.
  - `A001_09222312_C006.MP4` → `20261020_A001_09222312_C006.mp4`
- 같은 이름이 이미 있으면 덮어쓰지 않고 `_2`, `_3`을 붙입니다.

## 중복 처리

원본 이름과 크기가 같은 파일은 한 개만 남깁니다. 먼저 들어온 파일을 FOOTAGE에 두고, 나머지는 DUPLICATES로 옮깁니다. 이미 정리된 파일과 비교하므로 같은 파일을 다시 넣어도 중복으로 걸러집니다.

## 명령 (Claude가 실행)

| 하고 싶은 일 | 명령 |
|---|---|
| INBOX 확인 (옮기지 않음) | `python3 reels/reels.py inbox` |
| 정리 시작 | `python3 reels/reels.py ingest --yes` |
| 대본을 JSON으로 변환·검사 | `python3 reels/reels.py script import <대본 파일> --id <릴스 ID>` |
| 대본 JSON 다시 검사 | `python3 reels/reels.py script check <JSON 파일>` |
| Gemini 모델 확인 | `python3 reels/reels.py check` |

## 흐름

1. 사용자가 촬영 파일을 INBOX에 넣습니다.
2. "넣었어"라고 말하면 Claude가 `inbox`로 목록을 보여 주고 "정리를 시작할까요?"라고 묻습니다.
3. "시작해"라고 하면 `ingest --yes`를 실행합니다.
4. 대본이 확정되면 파일을 보내고 `script import`로 JSON을 만듭니다.

## 설정

- `reels/config.json`: 루트 경로, 영상 확장자, 나레이션 쉼 시간, 목표 밝기
- `reels/.env`: API 키 (GitHub에 올라가지 않습니다)

```
GEMINI_API_KEY=여기에_키
ELEVENLABS_API_KEY=여기에_키
```

## 설치

```
pip3 install -r reels/requirements.txt
```

테스트: `python3 -m unittest discover -s reels/tests -v`
