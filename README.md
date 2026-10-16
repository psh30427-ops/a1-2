# 남양주 하루 여행 추천 (travel-recommender)

날짜를 입력하면 **경기도 남양주시 안의 읍/면/동 한 곳**을 추천하고, 그 지역의 맛집과 하루 일정을 담은 마크다운 리포트를 만들어 주는 Python CLI입니다.

## 개요

1. **Gemini**가 추천 지역, 날씨, 행사(1~3개), 추천 이유(2~4문장)를 JSON으로 답합니다.
   - `recommended_city`가 `"남양주시"`로 시작하는지만 검사합니다.
   - JSON이 코드블록(```json)으로 감싸져 와도 처리하며, 파싱·검증에 실패하면 **1회 재시도**합니다.
   - **날씨는 실시간 예보가 아니라 해당 날짜(계절)의 일반적인 기후 경향**입니다. Gemini에게도 그렇게 쓰라고 요청합니다.
2. **카카오 로컬 API** 키워드 검색(`category_group_code=FD6`, 음식점)으로 `"남양주 {추천 지역} 맛집"`을 검색해 음식 종류가 겹치지 않게 약 5곳을 고릅니다.
   - 검색이 실패하거나 0건이어도 프로그램은 계속 실행되고, 이유가 `errors`에 기록됩니다.
3. **Gemini**가 최종 리포트(추천 지역·이유, 날씨, 행사, 맛집, 오전/오후/저녁 일정)를 작성합니다.
   - 이 단계가 실패하면 가진 데이터로 **기본 리포트**를 대신 저장합니다. 맛집이 없으면 "데이터 없음"으로 표시됩니다.

## 실행 방법

Python 3.9 이상이 필요합니다.

```bash
# 1) 가상환경 만들기 및 의존성 설치
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 2) 키 설정 (아래 '키 설정' 참고)

# 3) 실행
.venv/bin/python main.py -date "2026-10-20"
```

- `-date`는 필수이며 `YYYY-MM-DD` 형식이어야 합니다. 형식이 틀리면 usage를 출력하고 종료합니다.
- 키가 없으면 설정 방법을 안내하고 바로 종료합니다.

### Gemini 모델 바꾸기

기본 모델은 `gemini-2.5-flash`이며 환경변수 `GEMINI_MODEL`로 바꿀 수 있습니다.

```bash
GEMINI_MODEL=gemini-2.5-pro .venv/bin/python main.py -date "2026-10-20"
```

> **HTTP 404가 나오면 `GEMINI_MODEL`을 바꿔보세요.** 모델 이름이 바뀌었거나 더 이상 제공되지 않는 경우입니다.

## 키 설정

필요한 키는 두 가지입니다.

| 환경변수 | 발급처 |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio |
| `KAKAO_REST_API_KEY` | Kakao Developers → 내 애플리케이션 → REST API 키 |

**방법 1 — `.env` 파일**

```bash
cp .env.example .env
# 편집기로 .env 를 열어 값을 채우세요.
```

**방법 2 — 터미널 환경변수**

```bash
export GEMINI_API_KEY="발급받은_키"
export KAKAO_REST_API_KEY="발급받은_키"
```

둘 다 설정되어 있으면 터미널 환경변수가 우선합니다.

## 결과 확인 방법

실행하면 진행 로그와 저장 경로가 출력되고, `results/` 폴더에 두 파일이 생깁니다.

- `results/{날짜}_{실행시각}_raw.json` — `recommendation`, `restaurants`, `errors` 원본 데이터
- `results/{날짜}_{실행시각}_report.md` — 최종 리포트

`errors`에는 단계(`stage`)와 HTTP 상태 코드 같은 짧은 이유만 기록되며, API 응답 본문은 저장하지 않습니다.

## 오프라인 테스트

`requests`를 mock 하므로 키와 네트워크 없이 실행됩니다. 실제 API는 호출하지 않습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

맛집 0건, 카카오 HTTP 오류/네트워크 오류, Gemini JSON 파싱 실패 후 재시도 성공/실패, Gemini HTTP 404, 키 누락 시 종료, 잘못된 날짜 형식, 결과·로그에 키가 남지 않는지 등을 검사합니다.

## 키 유출 주의사항

- `.env`는 `.gitignore`에 들어 있습니다. **절대 커밋하지 마세요.** `git add` 전에 `git status`로 확인하세요.
- 키는 URL에 넣지 않고 헤더(`x-goog-api-key`, `Authorization: KakaoAK ...`)로만 보냅니다.
- 로그, 결과 파일, 오류 메시지에는 키를 남기지 않습니다. 오류는 HTTP 상태 코드(또는 예외 종류)만 기록합니다.
- 키를 채팅, 이슈, 스크린샷에 붙여넣지 마세요. 노출됐다면 즉시 발급처에서 키를 폐기하고 재발급하세요.
- `.env.example`에는 값을 넣지 마세요.

## 한계

- **날씨는 실시간 예보가 아닙니다.** Gemini가 알려주는 계절 경향일 뿐이므로 여행 전에 기상청 예보를 확인하세요.
- **행사 정보는 Gemini가 생성한 것**이라 실제 개최 여부·일정이 다를 수 있습니다.
- **맛집은 평점 순이 아니라 카카오 키워드 검색 정확도 순**입니다. 맛이나 인기를 보장하지 않습니다.
- 읍/면/동 이름은 코드에서 별도로 검증하지 않습니다(`"남양주시"`로 시작하는지만 확인).
