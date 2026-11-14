import numpy as np

from pantanal_sar import change


def test_db_and_ratio():
    a = np.array([[1.0, 0.1]], dtype="float32")
    assert np.allclose(change.to_db(a), [[0, -10]])
    assert np.allclose(change.log_ratio_db(a, a), 0)


def test_water_threshold_bimodal():
    rng = np.random.default_rng(0)
    v = np.concatenate([rng.normal(-20, 1, 5000), rng.normal(-8, 1, 5000)])
    t = change.water_threshold(v.reshape(100, 100))
    assert -17 < t < -11


def test_confirm_objects_keeps_whole_patch():
    cand = np.zeros((10, 10), bool); cand[2:6, 2:6] = True; cand[8, 8] = True
    ev = np.zeros_like(cand); ev[3, 3] = True
    out = change.confirm_objects(cand, ev, min_px=2)
    assert out[2:6, 2:6].all() and not out[8, 8]
