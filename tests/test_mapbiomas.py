import pytest

from pantanal_sar import mapbiomas as mb


def test_normalize_sorts_and_forces_day_one():
    r = mb.normalize([("2020-03-15", "10.5"), ("2020-01-01", 3), ("2020-02-01", None)], "5")
    assert [x["date"] for x in r] == ["2020-01-01", "2020-03-01"]
    assert r[1]["water_km2"] == 10.5 and r[0]["collection"] == "5"


def test_duplicate_month_rejected():
    with pytest.raises(ValueError):
        mb.normalize([("2020-03-01", 1), ("2020-03-20", 2)], "5")


def test_write_header(tmp_path):
    p = mb.write(mb.normalize([("2020-01-01", 1)], "5"), tmp_path / "x.csv")
    assert p.read_text().splitlines()[0] == "date,water_km2,source,collection"
