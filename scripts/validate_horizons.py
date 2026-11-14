import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lunar_core as lc  # noqa: E402

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
BODIES = {"sun": "10", "earth": "399"}
START, STOP, STEP = "2027-01-01", "2028-01-01", "1 d"
TIME_FORMATS = ("%Y-%b-%d %H:%M", "%Y-%b-%d %H:%M:%S", "%Y-%b-%d %H:%M:%S.%f")


def parse_time(text):
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Horizons time: {text!r}")


def horizons(body_id, lat, lon):
    """Airless apparent azimuth/elevation of a body from a lunar surface site."""
    params = {
        "format": "json",
        "COMMAND": f"'{body_id}'",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "OBSERVER",
        "CENTER": "'coord@301'",
        "COORD_TYPE": "GEODETIC",
        "SITE_COORD": f"'{lon % 360:.6f},{lat:.6f},0'",
        "START_TIME": f"'{START}'",
        "STOP_TIME": f"'{STOP}'",
        "STEP_SIZE": f"'{STEP}'",
        "QUANTITIES": "'4'",
        "TIME_TYPE": "UT",
        "CSV_FORMAT": "YES",
        "EXTRA_PREC": "YES",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as resp:
        text = json.load(resp)["result"]
    if "$$SOE" not in text:
        raise RuntimeError("Horizons returned no ephemeris:\n" + text[:2000])
    rows = []
    for line in text.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines():
        fields = [f.strip() for f in line.split(",")]
        numbers = []
        for f in fields[1:]:
            try:
                numbers.append(float(f))
            except ValueError:
                pass                      # daylight / interfering-body flags
        rows.append((parse_time(fields[0]), numbers[-2], numbers[-1]))
    return pd.DataFrame(rows, columns=["time", "az", "alt"])


def skyfield(eph, body, lat, lon, times):
    t = eph.ts.from_datetimes(list(times))
    site = eph.moon + eph.pc.build_latlon_degrees(eph.frame, lat, lon)
    target = eph.sun if body == "sun" else eph.earth
    alt, az, _ = site.at(t).observe(target).apparent().altaz()
    return az.degrees, alt.degrees


def main():
    eph = lc.Ephemeris()
    out = []
    for s in lc.load_sites().itertuples():
        for body, body_id in BODIES.items():
            ref = horizons(body_id, s.lat, s.lon)
            az, alt = skyfield(eph, body, s.lat, s.lon, ref["time"])
            d_alt = alt - ref["alt"].to_numpy()
            d_az = (az - ref["az"].to_numpy() + 180) % 360 - 180
            out.append({
                "site": s.name,
                "body": body,
                "samples": len(ref),
                "max_alt_diff_deg": float(np.abs(d_alt).max()),
                "max_az_diff_deg": float(np.abs(d_az).max()),
            })
            print(f"{s.name:20s} {body:6s} {len(ref):4d} samples  "
                  f"max |d alt| {out[-1]['max_alt_diff_deg']:.6f}°  "
                  f"max |d az| {out[-1]['max_az_diff_deg']:.6f}°")
            time.sleep(1)                 # be polite to the Horizons server

    res = pd.DataFrame(out)
    (ROOT / "docs").mkdir(exist_ok=True)
    res.to_csv(ROOT / "docs" / "validation_horizons.csv", index=False)
    print(f"\nPeriod {START} to {STOP}, step {STEP}, {len(res)} site/body pairs")
    print(f"Largest altitude difference: {res.max_alt_diff_deg.max():.6f}°")
    print(f"Largest azimuth difference:  {res.max_az_diff_deg.max():.6f}°")


if __name__ == "__main__":
    main()