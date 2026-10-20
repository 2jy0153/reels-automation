# 릴스 자동화

가방 브랜드 릴스를 만드는 자동화입니다. 기획과 대본 확정은 사람이 하고, 그다음 단계를 자동화합니다.
명령은 모두 Claude가 실행합니다. 사용자는 확인하고 "시작해"라고 말하면 됩니다.

## 폴더 구조 (SSD 안)

```
SOURCE_LIBRARY/
  INBOX/                       새 파일을 넣는 곳 (정리되면 비워짐)
  LIBRARY/
    VIDEO/YYYY-MM-DD/          영상 원본 (날짜별)
    PHOTO/YYYY-MM-DD/          사진 원본 (날짜별)
    _NO_DATE/                  날짜를 못 찾은 영상·사진. 직접 확인 후 옮김
    _UNSORTED/                 영상도 사진도 아닌 파일. 직접 확인 후 옮김
  PROXY/VIDEO/YYYY-MM-DD/      분석·편집용 720p 사본 (원본과 같은 이름)
  DUPLICATES/                  중복으로 빠진 파일. 확인 후 직접 지움
  CLIP_INDEX/                  태그 정보, 기록(ingest_log.json, move_log.json)
  REELS/<릴스 ID>/             릴스 1편 = 폴더 1개
```

원본은 수정·삭제하지 않습니다. 주제(BTS, 제품, 장소 등)로 폴더를 나누지 않고, 한 파일이 여러 주제에 속할 수 있어서 **태그**로 찾습니다.

## 날짜 찾는 순서

1. 파일명에 YYYYMMDD가 있으면 그 날짜를 씁니다.
2. 없으면 메타데이터(EXIF, 영상의 촬영 정보)를 `exiftool`로 읽습니다.
3. 둘 다 없으면 `_NO_DATE`에 넣습니다. 파일 수정일은 쓰지 않습니다.

## 파일 이름 규칙

`YYYYMMDD_나머지` 형식입니다. 시분초는 넣지 않습니다.

- 원래 이름에 촬영일(YYYYMMDD)이 있으면 그 날짜는 빼고, 맨 앞에 한 번만 붙입니다.
  - `IMG_20260904_150352.mp4` → `20260904_IMG_150352.mp4`
  - `20260904_150352.mp4` → `20260904_150352.mp4`
- 파일명에 날짜가 없고 메타데이터에서 찾은 경우에도 맨 앞에 날짜를 붙입니다.
  - `A001_09222312_C006.MP4` (메타데이터 20261020) → `20261020_A001_09222312_C006.mp4`
- 같은 이름이 이미 있으면 덮어쓰지 않고 `_2`, `_3`을 붙입니다.

## 중복 처리

원본 이름과 크기가 같은 파일은 한 개만 남기고 나머지는 `DUPLICATES/`로 옮깁니다. 아무것도 지우지 않으므로 확인 후 직접 지우면 됩니다. 이미 정리된 파일과도 비교합니다.

## 명령 (Claude가 실행)

| 하고 싶은 일 | 명령 |
|---|---|
| INBOX 확인 (옮기지 않음) | `python3 reels/reels.py inbox` |
| 정리 시작 | `python3 reels/reels.py ingest --yes` |
| 대본을 JSON으로 변환·검사 | `python3 reels/reels.py script import <대본 파일> --id <릴스 ID>` |

## 대본 형식

대본 파일(`.md` 또는 `.txt`)은 두 형식을 모두 읽습니다.

1. **표 형식**: `시간 | 화면 | 대사 | 화면 자막` 열이 있는 마크다운 표
2. **일반 텍스트**:
   - 시간 표시가 있으면 그대로 씁니다. 예: `0~3초 대사`, `[3~6] 대사`
   - 시간 표시가 없으면 문단마다 한 줄로 보고, 글자 수로 예상 시간(초당 6자)을 잡습니다. 이 경우 검사 결과에 "예상 시간"이라고 표시됩니다.
   - `자막:`, `화면:`, `대사:` 줄로 칸을 나눌 수 있습니다.
   - `본문`, `썸네일` 섹션과 `#해시태그` 줄을 인식합니다.
| 대본 JSON 다시 검사 | `python3 reels/reels.py script check <JSON 파일>` |
| 나레이션 생성 (확인만) | `python3 reels/reels.py voice <릴스 ID>` |
| 나레이션 생성 (실행) | `python3 reels/reels.py voice <릴스 ID> --yes` |
| Gemini 모델 확인 | `python3 reels/reels.py check` |

## 흐름

1. 사용자가 촬영 파일을 INBOX에 넣습니다.
2. "넣었어"라고 말하면 Claude가 `inbox`로 목록을 보여 주고 "정리를 시작할까요?"라고 묻습니다.
3. "시작해"라고 하면 `ingest --yes`를 실행합니다.
4. 대본이 확정되면 파일을 보내고 `script import`로 JSON을 만듭니다.

## 나레이션 (voice)

목표 시간에 맞추지 않습니다. 음성을 먼저 만들고, 들어 본 뒤 배속을 정합니다.

1. `voice <ID> --yes`: 줄마다 원래 속도의 음성을 만들어 `voice/raw/`에 저장합니다. 이미 있는 음성은 다시 만들지 않습니다.
2. `voice/raw/`의 음성을 듣고, `voice <ID> --speed 1.1`처럼 배속을 정합니다. 음성 API는 다시 부르지 않고 `voice/NN.mp3`와 타임라인만 만듭니다.
3. `voice/timeline.json`에 실제 음성 길이 기준의 줄별 시작·끝 시간이 기록됩니다. 줄 사이 쉼은 `pause_seconds`(0.3초), 질문으로 끝나는 줄 뒤는 `pause_after_question_seconds`(0.6초)입니다.

목소리는 `config.json`의 `elevenlabs_voice_id`에 넣어야 합니다. 비어 있으면 원본 음성 생성 단계에서 중단합니다.

## 음성 자르기와 자막 (split-voice, srt)

- `split-voice <ID>`: `voice` 폴더의 전체 음성 mp3 하나를 대본 문단 수만큼 나눕니다. 문단 사이에서 가장 긴 무음 구간을 자를 자리로 씁니다. 결과를 먼저 보여 주고, `--yes`를 붙여야 `voice/raw/NN.mp3`로 저장합니다.
- 무음 구간 수가 문단 수보다 적으면 중단합니다. 캡컷에서 문단 사이 쉼을 늘려 다시 만들거나, 자를 위치를 직접 정해 주세요.
- `srt <ID>`: `voice/timeline.json`의 실제 음성 시간으로 `subtitles/<ID>.srt`를 만듭니다. 자막 문구는 대사 전체입니다. 먼저 `voice <ID> --speed 값`을 실행해야 합니다.

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
