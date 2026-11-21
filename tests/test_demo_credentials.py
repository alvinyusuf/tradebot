import pytest

from tradebot.demo_credentials import demo_credentials


def test_only_demo_credentials_are_used(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.delenv("BINANCE_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_API_SECRET", raising=False)
    path.write_text(
        "BINANCE_API_KEY=live-fixture\nBINANCE_API_SECRET=live-fixture\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="belum tersedia") as error:
        demo_credentials(path)
    assert "live-fixture" not in str(error.value)
    with path.open("a", encoding="utf-8") as file:
        file.write(
            'BINANCE_DEMO_API_KEY="demo-fixture"\nexport BINANCE_DEMO_API_SECRET=demo-secret-fixture\n'
        )
    assert demo_credentials(path) == ("demo-fixture", "demo-secret-fixture")
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "process-demo-fixture")
    assert demo_credentials(path)[0] == "process-demo-fixture"
