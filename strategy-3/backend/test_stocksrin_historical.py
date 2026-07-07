"""Tests for StocksRin CSV candle parser."""

from app.services.stocksrin_historical import parse_chart_data, parse_csv_candle_row, unix_to_ist_iso


def test_parse_csv_row():
    row = ",1781501640,765.85,766.75,765.85,766.75,40,0"
    c = parse_csv_candle_row(row)
    assert c is not None
    assert c["timestamp"] == 1781501640
    assert c["open"] == 765.85
    assert c["high"] == 766.75
    assert c["low"] == 765.85
    assert c["close"] == 766.75
    assert c["volume"] == 40.0
    assert c["oi"] == 0.0
    assert "+05:30" in c["time"] or "T" in c["time"]


def test_parse_chart_data_list():
    data = [",1781501640,100,110,90,105,10,0", ",1781502240,105,115,100,112,20,5"]
    candles = parse_chart_data(data)
    assert len(candles) == 2
    assert candles[0]["close"] == 105.0
    assert candles[1]["close"] == 112.0


def test_unix_to_ist():
    iso = unix_to_ist_iso(1782963900)
    assert "2026" in iso
