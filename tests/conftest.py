"""테스트는 개발자의 .env 에 영향받지 않아야 한다.

예전에 .env 를 DATA_SOURCE=sheets 로 바꿨더니 화면 테스트가 수집 단계에서
깨졌다. 테스트는 항상 로컬 CSV + MOCK 으로 돌린다 (API 비용 0원).
개별 테스트는 monkeypatch 로 이 값을 덮어쓸 수 있다.
"""
import os

os.environ["DATA_SOURCE"] = "csv"
os.environ["MOCK_AI"] = "true"
os.environ.pop("GOOGLE_SHEETS_ID", None)
