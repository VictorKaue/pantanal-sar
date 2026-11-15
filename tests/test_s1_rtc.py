import numpy as np
import rasterio

from pantanal_sar import s1_rtc


def test_mosaic_linear_averages_and_keeps_nan():
    a = np.array([[0.01, np.nan], [np.nan, 0.1]], dtype=np.float32)
    b = np.array([[0.03, np.nan], [0.1, np.nan]], dtype=np.float32)
    m = s1_rtc.mosaic_linear([a, b])
    assert abs(m[0, 0] - 0.02) < 1e-7 and np.isnan(m[0, 1]) and abs(m[1, 0] - 0.1) < 1e-7


def test_write_linear_roundtrip_small_error(tmp_path):
    lin = np.array([[0.0123456, np.nan], [0.0001, 0.2]], dtype=np.float32)
    f = tmp_path / "x_VV.tif"
    s1_rtc.write_linear(f, lin, (500000.0, 8000000.0, 2, 2))
    with rasterio.open(f) as d:
        a = d.read(1)
        assert d.crs.to_epsg() == 32721 and d.res == (30.0, 30.0)
    assert np.isnan(a[0, 1]) and np.allclose(a[~np.isnan(a)], lin[~np.isnan(lin)], rtol=5e-4)


def test_batches_priority():
    ds = ["2023-01-10", "2024-04-02", "2026-09-26", "2026-09-30", "2025-08-05"]
    b = dict(s1_rtc.batches(ds))
    assert b["1_perto_NISAR_2026"] == ["2026-09-26", "2026-09-30"]
    assert b["2_cheia_seca"] == ["2024-04-02", "2025-08-05"] and b["3_restante"] == ["2023-01-10"]


def test_to_grid_places_pixels(tmp_path):
    from rasterio.transform import Affine
    grid = (500000.0, 8000000.0, 4, 4)
    data = np.full((4, 4), 0.05, dtype=np.float32)
    data[0, 0] = -9999
    with rasterio.MemoryFile() as mf:
        with mf.open(driver="GTiff", height=4, width=4, count=1, dtype="float32", crs="EPSG:32721",
                     transform=Affine(30, 0, 500000.0, 0, -30, 8000000.0), nodata=-9999) as d:
            d.write(data, 1)
        out = s1_rtc.to_grid(mf.read(), grid)
    assert np.isnan(out[0, 0]) and abs(out[3, 3] - 0.05) < 1e-6
