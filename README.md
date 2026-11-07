# AI Quote Maker

[![tests](https://img.shields.io/badge/tests-22%20passed-brightgreen)](tests/)

베트남 B2B 사무용품 유통사를 가정한 AI 견적서 자동 생성 도구.
고객의 자연어 문의 → 상품 매칭 → 금액 계산 → PDF 견적서.

## 지금 돌아가는 것

| 화면 | 상태 |
| --- | --- |
| Dashboard | ✅ 상품/고객 수, 재고 주의 상품, 진행 현황 |
| New Quotation | ✅ 문의 입력 → Claude 구조화 분석 (상품명·수량·납기 표현) |
| Product Search | ✅ 상품명·카테고리 검색 |
| Settings / Connection | ✅ 연결 상태, 회사 정보, 데이터 다시 읽기 |
| Quotation Preview | 🚧 7단계 |

API 키 없이도 실행됩니다 (`DATA_SOURCE=csv`, `MOCK_AI=true`). Mock 결과는 화면에
🧪 배지로 실제 API 결과와 구분됩니다.

## 실행 방법

```bash
# 1) 가상환경
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2) 패키지
pip install -r requirements.txt

# 3) 환경변수 파일 만들기 (값은 그대로 두면 CSV + MOCK 모드로 동작)
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

# 4) 실행
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다.

## 테스트

```bash
pytest -q
```

데이터 검증 8개 + AI 추출 검증 9개 + 화면 렌더링 5개, 총 22개.
테스트는 실제 Claude API를 호출하지 않습니다 (비용·속도·재현성).

## 폴더 구조

```
quote_maker/
├─ app.py                 Streamlit 화면 (여기에는 계산 로직을 두지 않는다)
├─ core/
│  ├─ config.py           .env 읽기, API 키 마스킹
│  ├─ datasource.py       상품/고객/설정 읽기 + 데이터 검증
│  └─ ai.py               Claude 구조화 출력으로 문의 분석
├─ data/                  가상 데이터 (Google Sheets 연결 전 테스트용)
│  ├─ products.csv
│  ├─ customers.csv
│  └─ settings.csv
├─ tests/
├─ .env.example
└─ requirements.txt
```

**설계 원칙**: 비즈니스 로직은 모두 `core/` 에 둡니다. 2단계에서 UI를 FastAPI로
바꿀 때 `core/` 를 그대로 가져다 씁니다. `core/` 안에서는 `streamlit` 을
import 하지 않습니다.

## 데이터 구조

`data/*.csv` 와 Google Sheets의 탭 구조는 **완전히 동일**합니다. CSV로 먼저
개발하고, 준비되면 `.env` 의 `DATA_SOURCE` 만 `sheets` 로 바꿉니다.

### Products 탭
`product_id` · `product_name` · `category` · `unit_price` · `cost_price` ·
`stock_quantity` · `currency` · `active`

### Customers 탭
`customer_id` · `company_name` · `contact_name` · `email` ·
`customer_tier` · `discount_rate`

### Settings 탭 (key, value 2열)
`company_name` · `company_address` · `company_email` · `company_phone` ·
`quotation_valid_days` · `default_currency` · `tax_rate`

규칙:
- 첫 행은 컬럼명입니다.
- `product_id`, `customer_id` 는 중복되지 않아야 합니다 (중복 시 첫 행만 사용 + 경고).
- 모든 금액은 VND, **세전 가격**입니다. 세율은 코드에 박아두지 않고 Settings의
  `tax_rate` 를 읽습니다.
- `discount_rate` 는 0~1 사이 소수입니다 (10% → `0.10`).
- 범위를 벗어난 값은 앱이 경고를 띄우고 안전한 기본값으로 처리합니다.

데이터에는 테스트용 함정이 일부러 들어 있습니다: 재고 0인 비활성 상품
(`P-1070`), 재고 한 자리 상품 3개, 이름이 비슷한 상품들
(Wireless/Wired Keyboard, Wireless/Wired/Ergonomic Mouse) — 4단계 상품 매칭에서
사용합니다.

## Google Sheets 연결 (2단계에서 진행)

지금 하지 않아도 됩니다. 2단계에서 함께 진행하며, 필요한 준비는 다음과 같습니다.

1. Google Sheets에 스프레드시트를 만들고 탭 3개를 위 구조대로 생성
   (`data/*.csv` 를 각 탭에 그대로 붙여넣으면 됩니다)
2. [Google Cloud Console](https://console.cloud.google.com) → 프로젝트 생성 →
   **Google Sheets API** 와 **Google Drive API** 사용 설정
3. 사용자 인증 정보 → **서비스 계정** 생성 → 키 추가 → JSON 다운로드
4. 다운로드한 파일을 `credentials/service_account.json` 으로 저장
5. 스프레드시트 **공유** → JSON 안의 `client_email` 주소를 **보기(Viewer)** 권한으로 추가
6. `.env` 수정:
   ```
   DATA_SOURCE=sheets
   GOOGLE_SHEETS_ID=<주소창의 /d/ 와 /edit 사이 문자열>
   ```

시트는 **읽기 전용**으로만 사용합니다 (쓰기 코드를 두지 않습니다).

## Claude API 연결 ✅

1. [console.anthropic.com](https://console.anthropic.com) → API Keys → 키 발급
2. `.env` 수정:
   ```
   MOCK_AI=false
   ANTHROPIC_API_KEY=sk-ant-...
   CLAUDE_MODEL=claude-opus-5-5     # 비용을 줄이려면 claude-sonnet-5-5
   ```

`MOCK_AI=true` 면 API 호출 없이 고정 예시로 전체 흐름을 연습할 수 있고,
화면에 🧪 **MOCK 모드** 배지가 표시됩니다.

### AI에게 맡기지 않는 것

`core/ai.py` 의 추출 스키마에는 **가격·재고·할인·세금 필드가 없습니다.** 구조적으로
AI가 금액을 만들어낼 수 없습니다. 납기도 고객이 쓴 표현을 그대로 옮기며 실제 날짜로
변환하지 않습니다. 모든 금액 계산은 Python 코드가 수행합니다.

## 보안

- `.env` 와 `credentials/` 는 `.gitignore` 에 등록되어 있습니다. **절대 커밋하지 마세요.**
- API 키는 화면에 앞 7자 + 뒤 4자만 표시합니다 (`core/config.py` 의 `masked_key`).
- Google Sheets 연결 오류는 예외 타입만 보여줍니다 (토큰이 메시지에 섞여 나오는 것을 막기 위함).

## 개발 진행 상황

1. ~~프로젝트 골격 + 가상 데이터~~ ✅
2. ~~Claude API로 문의 → JSON 구조화~~ ✅
3. Google Sheets 실제 연결 — ⏸️ 스프레드시트를 Google Sheets 형식으로 변환 필요
4. 상품 매칭 + 재고 비교 ← **다음**
5. 가격 계산 (할인 → 세금 순서)
6. 견적 검토 화면
7. PDF 생성 + 이메일 초안 (한/영/베)
8. 오류 처리 + 배포 준비
