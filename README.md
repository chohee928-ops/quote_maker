# AI Quote Maker

베트남 B2B 사무용품 유통사를 가정한 **AI 견적서 자동 생성 도구**.

고객의 자연어 문의 → Claude가 상품·수량 추출 → 실제 상품 데이터와 매칭 →
재고 확인 → 금액 계산 → 전문 PDF 견적서 + 3개 언어 이메일 초안.

```
pip install -r requirements.txt
streamlit run app.py
```

API 키 없이 바로 실행됩니다 (`DATA_SOURCE=csv`, `MOCK_AI=true`).

---

## 화면

| 화면 | 내용 |
| --- | --- |
| **Dashboard** | 상품/고객 수, 재고 주의 상품, 진행 현황 |
| **New Quotation** | 6단계 위저드 — 문의 입력 → AI 분석 → 상품 매칭 → 재고 확인 → 견적 검토 → PDF·이메일 |
| **Product Search** | 상품명·카테고리·ID 검색 |
| **Quotation Preview** | 마지막 견적 요약, PDF 재다운로드 |
| **Settings / Connection** | 연결 상태 진단, 회사 정보, 캐시 비우기 |

---

## 이 프로젝트의 핵심 설계

### 1. AI는 숫자를 만들 수 없다 — 프롬프트가 아니라 구조로 막는다

`core/ai.py` 의 추출 스키마에는 **가격·재고·할인·세금 필드가 아예 없습니다.**
"가격을 만들지 마"라고 부탁하는 대신, 만들어낼 자리를 없앴습니다.

```
AI가 하는 일   : 자연어 → {상품명, 수량, 납기 표현, 요구사항}
Python이 하는 일: 상품 조회, 가격, 재고, 할인, 세금, 합계 전부
```

상품 가격은 항상 Products 테이블의 `unit_price` 를 그대로 씁니다
(`test_price_always_comes_from_the_table` 로 검증).

### 2. 확정되지 않은 것을 확정된 것처럼 말하지 않는다

- **납기**: 고객이 쓴 표현("다음 주까지")을 그대로 보관하고 날짜로 변환하지
  않습니다. PDF와 이메일 모두 "재고 확인 후 안내"로 표기합니다.
- **재고 부족**: 화면·PDF·이메일 3곳 모두에 부족 수량과 함께 표시됩니다.
  숨겨지지 않습니다.
- **상품 미확정**: 유사 상품이 여러 개면 사용자가 직접 고를 때까지 견적에
  들어가지 않고, "확인 필요"로 견적서에 남습니다.

### 3. UI와 비즈니스 로직이 분리되어 있다

`core/` 안에서는 **`streamlit` 을 import 하지 않습니다.** Dashboard의 숫자
계산조차 화면 코드가 아니라 `Catalog` 객체의 메서드입니다. 2단계에서 FastAPI로
UI를 바꿀 때 `core/` 를 그대로 가져갑니다.

### 4. 금액은 정수로만 계산한다

VND는 보조 단위가 없습니다. float로 비율을 곱하면 합계에서 오차가 드러나므로
금액은 전부 정수로 두고, 비율 곱셈만 `Decimal` + `ROUND_HALF_UP` 으로
반올림합니다.

**적용 순서** (금액이 달라지므로 명시):

```
품목합계 = 단가 × 수량
소계     = Σ 품목합계
할인     = round(소계 × 할인율)
과세표준 = 소계 − 할인
세금     = round(과세표준 × 세율)        ← 세율은 Settings의 tax_rate
합계     = 과세표준 + 세금
```

즉 **할인을 먼저 적용하고, 할인된 금액에 세금을 매깁니다.**

---

## 폴더 구조

```
quote_maker/
├─ app.py                   Streamlit 화면 (계산 로직 없음)
├─ core/                    ← UI를 바꿔도 그대로 재사용하는 부분
│  ├─ config.py             .env / Secrets 읽기, API 키 마스킹
│  ├─ datasource.py         CSV·Google Sheets 공통 로더 + 데이터 검증
│  ├─ ai.py                 Claude 구조화 출력으로 문의 분석
│  ├─ matching.py           상품명 → 실제 상품 매칭 + 재고 비교
│  ├─ pricing.py            할인·세금·합계 계산 (정수 연산)
│  ├─ pdf.py                ReportLab 견적서 생성
│  └─ email_draft.py        한/영/베 이메일 초안
├─ data/                    가상 데이터 (Sheets 연결 전 테스트용)
├─ assets/fonts/            NotoSansKR.ttf (한글+베트남어, 배포에 필요)
├─ tests/                   테스트 91개
├─ .streamlit/              테마 + 배포용 Secrets 예시
├─ .env.example
└─ requirements.txt
```

---

## 테스트

```bash
pytest -q        # 91 passed
```

| 파일 | 개수 | 검증하는 것 |
| --- | --- | --- |
| `test_datasource.py` | 8 | 중복 ID, 빈 셀, 범위 밖 할인율, 필수 컬럼 누락 |
| `test_ai.py` | 9 | 수량 0/음수/비정상, 항목 수 제한, **스키마에 가격 필드 없음** |
| `test_matching.py` | 12 | 모호한 상품, 단종 상품 자동선택 금지, 부족 수량 |
| `test_pricing.py` | 19 | 손 검산 금액, 할인→세금 순서, 반올림, 계산 중단 조건 |
| `test_pdf.py` | 11 | **폰트 글리프 전수 검사**, PDF 텍스트 왕복 추출 |
| `test_email_draft.py` | 18 | 3개 언어, 금액 일치, 납기 미약속 |
| `test_app_renders.py` | 5 | 5개 화면 렌더링 |
| `test_end_to_end.py` | 9 | 명세의 최종 완료 조건 9개 시나리오 전체 |

**테스트는 실제 Claude API를 호출하지 않습니다** (`MOCK_AI=true` 강제 주입).
돌리는 데 비용이 들지 않습니다.

---

## 폰트 — 이 프로젝트에서 가장 까다로웠던 부분

한글과 베트남어를 **동시에** 커버하는 폰트가 필요합니다. 실제로 검사한 결과:

| 폰트 | 영문 | 한글 | 베트남어 |
| --- | --- | --- | --- |
| malgun.ttf (맑은 고딕) | ✅ | ✅ | ❌ `ệ ễ ị ư` 없음 |
| arial.ttf | ✅ | ❌ | ✅ |
| gulim.ttc | ✅ | ✅ | ❌ |
| **NotoSansKR.ttf** | ✅ | ✅ | ✅ |

게다가 Streamlit Cloud는 리눅스라 `C:/Windows/Fonts` 가 **아예 없습니다.**
그래서 `assets/fonts/NotoSansKR.ttf` (10MB, SIL OFL 라이선스)를 프로젝트에
포함했습니다. 시스템 폰트에 의존하지 않습니다.

글리프 누락은 ReportLab이 오류를 내지 않고 **조용히 빈칸으로 렌더링**하므로,
테스트에서 데이터의 모든 문자가 폰트에 있는지 전수 검사하고, 생성된 PDF에서
텍스트를 다시 추출해 비교합니다.

---

## 데이터 구조

`data/*.csv` 와 Google Sheets 탭 구조는 **완전히 동일**합니다. CSV로 개발하고
`.env` 의 `DATA_SOURCE` 만 `sheets` 로 바꾸면 됩니다. 코드는 바뀌지 않습니다.

### Products
`product_id` · `product_name` · `category` · `unit_price` · `cost_price` ·
`stock_quantity` · `currency` · `active`

### Customers
`customer_id` · `company_name` · `contact_name` · `email` ·
`customer_tier` · `discount_rate`

### Settings (key, value 2열)
`company_name` · `company_address` · `company_email` ·
`quotation_valid_days` · `default_currency` · `tax_rate`

규칙:
- 첫 행은 컬럼명입니다.
- `product_id`, `customer_id` 는 고유해야 합니다 (중복 시 첫 행만 사용 + 경고).
- 금액은 VND, **세전 가격**입니다. 세율은 Settings의 `tax_rate` 를 읽습니다.
- `discount_rate` 는 0~1 소수입니다 (10% → `0.10`).
- 범위를 벗어난 값은 경고를 띄우고 안전한 기본값으로 처리합니다.
- Google Sheets는 **읽기 전용**으로만 사용합니다 (쓰기 코드가 없습니다).

### 데이터에 들어 있는 테스트 케이스

| 상품 | 상황 |
| --- | --- |
| P003 Monitor 22 inch | `active=FALSE` — 자동 선택되지 않음 |
| P025 Whiteboard Marker | 재고 0 — 전량 부족 |
| P007 Mouse Wireless | 재고 18개 — 30개 주문 시 12개 부족 |
| Monitor 24/27/22 | 이름 유사 — 사용자 선택 필요 |
| Keyboard Wired/Wireless/Mechanical | 이름 유사 |
| C003 김재훈, C005 Phạm Thị Hương | 한글·베트남어 이름 (PDF 폰트 검증) |

---

## Google Sheets 연결

> **현재 상태**: `.env` 에 설정된 파일이 **엑셀(.xlsx)** 이라 Sheets API가
> 거부합니다. 인증과 공유 권한은 정상입니다(403이 아니라 400).

```
APIError [400]: This operation is not supported for this document.
                The document must not be an Office file.
```

**해결 (1분)**: Drive에서 `product_info.xlsx` 를 열고 →
**파일 → Google Sheets로 저장** → 새로 생긴 파일의 주소창에서 `/d/` 와 `/edit`
사이 ID를 `.env` 의 `GOOGLE_SHEETS_ID` 에 넣고, 그 파일을 서비스 계정 이메일에
**보기(Viewer)** 권한으로 공유하세요. 탭 이름은 `Products` / `Customers` /
`Settings` 여야 합니다.

### 처음 설정하는 경우

1. [Google Cloud Console](https://console.cloud.google.com) → 프로젝트 생성
2. **Google Sheets API** 사용 설정
3. 사용자 인증 정보 → **서비스 계정** 생성 → 키 추가 → JSON 다운로드
4. `credentials/service_account.json` 으로 저장
5. 스프레드시트 공유 → JSON 안의 `client_email` 을 **보기** 권한으로 추가
6. `.env` 수정:
   ```
   DATA_SOURCE=sheets
   GOOGLE_SHEETS_ID=<주소창의 /d/ 와 /edit 사이>
   ```

---

## Claude API 연결

1. [console.anthropic.com](https://console.anthropic.com) → API Keys → 키 발급
2. `.env` 수정:
   ```
   MOCK_AI=false
   ANTHROPIC_API_KEY=sk-ant-...
   CLAUDE_MODEL=claude-opus-5-5     # 비용을 줄이려면 claude-sonnet-5-5
   ```

`MOCK_AI=true` 면 API 호출 없이 고정 예시로 전체 흐름을 연습할 수 있습니다.
Mock 결과와 실제 결과는 화면에서 🧪 / 🤖 배지로 **명확히 구분**되고, PDF에도
Mock 사용 여부가 표시됩니다.

**비용 주의**: `MOCK_AI=false` 면 "AI로 분석하기"와 "이메일 초안 작성"을 누를
때마다 실제 호출이 발생합니다.

---

## Streamlit Cloud 배포

1. 이 저장소를 GitHub에 푸시 (이미 되어 있습니다)
2. [share.streamlit.io](https://share.streamlit.io) → New app → 저장소 선택
3. Main file path: `app.py`
4. **App settings → Secrets** 에 `.streamlit/secrets.toml.example` 의 내용을
   채워 넣습니다. 이름은 `.env` 와 같습니다.
5. 서비스 계정 키는 파일로 올릴 수 없으므로 `GOOGLE_SERVICE_ACCOUNT_JSON` 에
   JSON 내용을 그대로 붙여넣습니다.

`app.py` 가 Secrets를 환경변수로 옮겨주므로 `core/` 코드는 로컬과 똑같이
동작합니다 (`core/` 는 `streamlit` 을 import 하지 않습니다).

---

## 보안

- `.env`, `credentials/`, `.streamlit/secrets.toml` 은 `.gitignore` 에 있습니다.
- API 키는 화면에 앞 7자 + 뒤 4자만 표시합니다 (`Config.masked_key`).
- 외부 API 오류는 예외 타입과 상태코드만 노출합니다 (키·토큰이 메시지에 섞여
  나오는 것을 막기 위함).
- Claude·Sheets 호출 **전에** 입력값을 검증합니다 (빈 문의, 길이 제한).
- AI 결과를 신뢰하지 않고 `validate_extraction()` 으로 걸러냅니다.
- Google Sheets는 읽기 전용입니다.

---

## 알려진 한계 (2단계에서 해결)

| 항목 | 현재 | 2단계 |
| --- | --- | --- |
| 견적번호 | 날짜+시각+난수 4자리 — 이론상 중복 가능 | DB 시퀀스 기반 고유 번호 |
| 금액 파싱 | 점(.)은 소수점으로만 해석. 베트남식 `3.200.000` 미지원 | 로케일 파서 |
| PDF 굵은 글씨 | 가변 폰트라 Bold 미적용, 크기·색으로 강조 | Bold 정적 폰트 추가 |
| 이메일 | 초안만 생성 | 실제 발송 |
| 로고 | `assets/logo.png` 가 없으면 회사명 약자 마크를 그림 | 실제 로고 |

`core/` 안의 `shortcut:` 주석으로도 표시되어 있습니다.
