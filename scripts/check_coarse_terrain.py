"""How much does the coarse terrain used for custom coordinates differ from the
full-resolution masks? Runs every listed site through both and compares one year.

Usage (from the project root):  python scripts/check_coarse_terrain.py
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lunar_core as lc  # noqa: E402

eph = lc.Ephemeris()
coarse = lc.CoarseTerrain()
print(f"{'site':26s} {'res':>5s} {'mean|dH|':>9s} {'sun fine/coarse':>17s} {'earth fine/coarse':>19s}")
for s in lc.load_sites().itertuples():
    fine_mask = lc.load_mask(s.id)
    coarse_mask, _ = coarse.horizon_mask(s.lat, s.lon)
    res = coarse.resolution_at(s.lat, s.lon)
    track = eph.sky_track(s.lat, s.lon, dt.date(2027, 1, 1), 365, 2)
    f = lc.visibility(track, fine_mask)
    c = lc.visibility(track, coarse_mask)
    dh = np.abs(coarse_mask["horizon"].to_numpy() - fine_mask["horizon"].to_numpy()).mean()
    print(f"{s.name:26s} {res:5.0f} {dh:8.2f}° "
          f"{100 * f.sun_vis.mean():7.1f}/{100 * c.sun_vis.mean():5.1f}%  "
          f"{100 * f.earth_vis.mean():8.1f}/{100 * c.earth_vis.mean():5.1f}%")