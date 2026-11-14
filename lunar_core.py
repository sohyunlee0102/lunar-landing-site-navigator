"""Core calculations for the Lunar Landing Site Navigator.

Sun and Earth positions come from Skyfield (JPL DE421, MOON_ME_DE421 frame).
Terrain comes from precomputed horizon masks (LOLA DEM, 360 azimuths per site).
A body counts as visible when any part of its disc clears the terrain horizon,
the same definition NASA uses for its LOLA polar illumination maps.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from skyfield.api import Loader
from skyfield.planetarylib import PlanetaryConstants

ASSETS = Path(__file__).parent / "assets"
SUN_RADIUS_DEG = 0.267      # apparent solar disc radius seen from the Moon
EARTH_RADIUS_DEG = 0.95     # apparent Earth disc radius seen from the Moon
MISSION_HOURS = 6.5 * 24    # planned Artemis III surface stay


class Ephemeris:
    """Sun and Earth as seen from a point on the lunar surface."""

    def __init__(self, ephem_dir=ASSETS / "ephemeris"):
        load = Loader(str(ephem_dir))
        self.ts = load.timescale()
        eph = load("de421.bsp")
        self.earth, self.moon, self.sun = eph["earth"], eph["moon"], eph["sun"]
        self.pc = PlanetaryConstants()
        self.pc.read_text(load("moon_080317.tf"))
        self.pc.read_text(load("pck00008.tpc"))
        self.pc.read_binary(load("moon_pa_de421_1900-2050.bpc"))
        self.frame = self.pc.build_frame_named("MOON_ME_DE421")

    def sky_track(self, lat, lon, start, days, step_hours):
        """Altitude/azimuth time series (degrees) of the Sun and Earth."""
        n = int(days * 24 / step_hours) + 1
        hours = np.arange(n) * step_hours
        t = self.ts.utc(start.year, start.month, start.day, hours)
        site = self.moon + self.pc.build_latlon_degrees(self.frame, lat, lon)
        out = {}
        for name, body in (("sun", self.sun), ("earth", self.earth)):
            alt, az, _ = site.at(t).observe(body).apparent().altaz()
            out[f"{name}_alt"] = alt.degrees
            out[f"{name}_az"] = az.degrees
        return pd.DataFrame(out, index=pd.DatetimeIndex(t.utc_datetime()))


SITE_FILES = (
    ("sites_refined.csv", "Artemis III candidate region"),
    ("missions.csv", "Past landing"),
)


def load_sites():
    """Artemis III candidate sites and past landings that have a precomputed horizon mask."""
    frames = []
    for fname, group in SITE_FILES:
        path = ASSETS / fname
        if path.exists():
            df = pd.read_csv(path)
            if "landed" not in df.columns:
                df["landed"] = None
            frames.append(df[["id", "name", "lat", "lon", "landed"]].assign(group=group))
    sites = pd.concat(frames, ignore_index=True)
    sites["has_terrain"] = sites["id"].apply(lambda i: (ASSETS / "masks" / f"{i}.csv").exists())
    # past landings outside the terrain model (e.g. Apollo) stay, on a smooth sphere
    sites = sites[sites["has_terrain"] | (sites["group"] == "Past landing")].reset_index(drop=True)
    sites.loc[~sites["has_terrain"], "group"] = "Past landing · smooth sphere, no terrain model"
    return sites


def load_mask(site_id):
    """Horizon mask for a listed site; a flat 0° horizon if no terrain mask exists."""
    path = ASSETS / "masks" / f"{site_id}.csv"
    if not path.exists():
        return pd.DataFrame({"az": np.arange(360.0), "horizon": np.zeros(360)})
    return pd.read_csv(path)


def horizon_at(mask, az):
    """Terrain horizon elevation at the given azimuths (wraps at 360)."""
    return np.interp(az, mask["az"].to_numpy(), mask["horizon"].to_numpy(), period=360)


def visibility(track, mask):
    """Add horizon, clearance and visibility columns to a sky track."""
    df = track.copy()
    df["sun_hz"] = horizon_at(mask, df["sun_az"].to_numpy())
    df["earth_hz"] = horizon_at(mask, df["earth_az"].to_numpy())
    # clearance > 0 means at least part of the disc is above the terrain
    df["sun_margin"] = df["sun_alt"] + SUN_RADIUS_DEG - df["sun_hz"]
    df["earth_margin"] = df["earth_alt"] + EARTH_RADIUS_DEG - df["earth_hz"]
    df["sun_vis"] = df["sun_margin"] > 0
    df["earth_vis"] = df["earth_margin"] > 0
    df["ops"] = df["sun_vis"] & df["earth_vis"]
    return df


def runs(flags):
    """(start index, length) of every consecutive True stretch."""
    f = np.asarray(flags, dtype=int)
    d = np.diff(np.concatenate([[0], f, [0]]))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip(starts, ends - starts))


def longest_run_hours(flags, step_hours):
    return max((n for _, n in runs(flags)), default=0) * step_hours


def hours_until_change(flags, step_hours):
    """Current state at the first sample and hours until it flips (None if never)."""
    f = np.asarray(flags)
    flips = np.where(f != f[0])[0]
    return bool(f[0]), (int(flips[0]) * step_hours if len(flips) else None)


def moment(df, i, step_hours):
    """Sun and Earth state at sample i, and hours until each next sets or rises."""
    row = df.iloc[i]
    sun_now, sun_change = hours_until_change(df["sun_vis"].iloc[i:], step_hours)
    earth_now, earth_change = hours_until_change(df["earth_vis"].iloc[i:], step_hours)
    return {
        "time": df.index[i],
        "sun_alt": float(row["sun_alt"]), "sun_az": float(row["sun_az"]),
        "sun_margin": float(row["sun_margin"]), "sun_now": sun_now, "sun_change_h": sun_change,
        "earth_alt": float(row["earth_alt"]), "earth_az": float(row["earth_az"]),
        "earth_margin": float(row["earth_margin"]), "earth_now": earth_now, "earth_change_h": earth_change,
    }


def mission_windows(df, step_hours, stay_hours=MISSION_HOURS):
    """Sunlit stretches long enough for a surface stay of `stay_hours` (default: Artemis III, 6.5 days)."""
    out = []
    last = len(df) - 1
    for s, n in runs(df["sun_vis"]):
        hours = n * step_hours
        if hours < stay_hours:
            continue
        seg = df.iloc[s:s + n]
        start = seg.index[0]
        out.append({
            "start": start,
            "land_by": start + pd.Timedelta(hours=hours - stay_hours),
            "hours": hours,
            "earth_pct": 100 * seg["earth_vis"].mean(),
            "blackout_h": longest_run_hours(~seg["earth_vis"], step_hours),
            "cut_off": s == 0 or s + n - 1 == last,
        })
    return out


def summarize(df, step_hours, stay_hours=MISSION_HOURS):
    """Comparison metrics for one site over the selected period."""
    sun_now, sun_change = hours_until_change(df["sun_vis"], step_hours)
    earth_now, earth_change = hours_until_change(df["earth_vis"], step_hours)
    return {
        "sunlight_pct": 100 * df["sun_vis"].mean(),
        "sun_elev_max": float(df["sun_alt"].max()),
        "sun_elev_mean_up": float(df.loc[df["sun_vis"], "sun_alt"].mean()) if df["sun_vis"].any() else None,
        "earth_pct": 100 * df["earth_vis"].mean(),
        "ops_pct": 100 * df["ops"].mean(),
        "longest_dark_h": longest_run_hours(~df["sun_vis"], step_hours),
        "longest_blackout_h": longest_run_hours(~df["earth_vis"], step_hours),
        "longest_sun_h": longest_run_hours(df["sun_vis"], step_hours),
        "mission_windows": mission_windows(df, step_hours, stay_hours),
        "sun_now": sun_now,
        "sun_change_h": sun_change,
        "earth_now": earth_now,
        "earth_change_h": earth_change,
    }


def landing_scan(df, step_hours, stay_hours=MISSION_HOURS):
    """Best landing option for each UTC day.

    For every possible landing time, checks whether the Sun stays visible for the
    whole 6.5-day stay. Returns, per day, the highest Earth-in-view percentage among
    landing times that stay sunlit (NaN if no landing time that day works).
    """
    n = int(round(stay_hours / step_hours))
    sun = df["sun_vis"].to_numpy(dtype=int)
    earth = df["earth_vis"].to_numpy(dtype=float)
    m = len(sun) - n + 1
    if m <= 0:
        return pd.Series(dtype=float)
    cs_sun = np.concatenate([[0], np.cumsum(sun)])
    cs_earth = np.concatenate([[0], np.cumsum(earth)])
    sunlit = (cs_sun[n:n + m] - cs_sun[:m]) == n
    earth_pct = 100 * (cs_earth[n:n + m] - cs_earth[:m]) / n
    score = pd.Series(np.where(sunlit, earth_pct, np.nan), index=df.index[:m])
    return score.resample("1D").max()


def load_offset_masks(site_id):
    """Horizon masks for points 100 m and 200 m around a site (None if not computed)."""
    path = ASSETS / "masks_offsets" / f"{site_id}.csv"
    return pd.read_csv(path) if path.exists() else None


def sensitivity(track, offsets):
    """Metrics at each offset point. Reuses the centre's sky track: over 200 m the
    Sun and Earth directions change by less than 0.01 degrees, so only terrain differs."""
    rows = []
    for (pid, east, north, height), g in offsets.groupby(["point", "east_m", "north_m", "height_m"]):
        mask = g[["az", "horizon"]].sort_values("az").reset_index(drop=True)
        df = visibility(track, mask)
        rows.append({
            "point": pid, "east_m": east, "north_m": north, "height_m": height,
            "sunlight_pct": 100 * df["sun_vis"].mean(),
            "earth_pct": 100 * df["earth_vis"].mean(),
            "ops_pct": 100 * df["ops"].mean(),
        })
    return pd.DataFrame(rows)


def load_terrain3d(site_id):
    """20 x 20 km terrain patch around a site in local east/north metres (None if missing)."""
    path = ASSETS / "terrain3d" / f"{site_id}.npz"
    if not path.exists():
        return None
    d = np.load(path)
    return {"east": d["east"], "north": d["north"], "z": d["z"], "h0": float(d["h0"])}


# ---------------------------------------------------------------- custom coordinates
R_MOON = 1737400.0
CUSTOM_ID = "custom"


def polar_xy(lat, lon):
    """Lunar latitude/longitude (deg) to south polar stereographic x, y (m), as in the LOLA DEMs."""
    lat, lon = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    rho = 2 * R_MOON * np.tan((np.pi / 2 + lat) / 2)
    return rho * np.sin(lon), rho * np.cos(lon)


def destination(lat, lon, az, dist):
    """Point reached from (lat, lon) along azimuth az (deg) after dist metres on the lunar sphere."""
    p1, l1 = np.radians(lat), np.radians(lon)
    th, dl = np.radians(az), np.asarray(dist, float) / R_MOON
    p2 = np.arcsin(np.sin(p1) * np.cos(dl) + np.cos(p1) * np.sin(dl) * np.cos(th))
    l2 = l1 + np.arctan2(np.sin(th) * np.sin(dl) * np.cos(p1), np.cos(dl) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), np.degrees(l2)


def _bilinear(grid, col, row):
    """Bilinear sample of an int16 grid (-32768 = no data); NaN outside or next to gaps."""
    out = np.full(row.shape, np.nan)
    r0, c0 = np.floor(row), np.floor(col)
    ok = (r0 >= 0) & (c0 >= 0) & (r0 < grid.shape[0] - 1) & (c0 < grid.shape[1] - 1)
    if not ok.any():
        return out
    r, c = r0[ok].astype(int), c0[ok].astype(int)
    fr, fc = row[ok] - r, col[ok] - c
    v = [grid[r + i, c + j].astype(float) for i, j in ((0, 0), (0, 1), (1, 0), (1, 1))]
    v = [np.where(x == -32768, np.nan, x) for x in v]
    out[ok] = (v[0] * (1 - fr) * (1 - fc) + v[1] * (1 - fr) * fc
               + v[2] * fr * (1 - fc) + v[3] * fr * fc)
    return out


class CoarseTerrain:
    """Down-sampled LOLA terrain (240 m to 80°S, 960 m to 60°S) for custom coordinates."""

    MIN_LAT = -60.0

    def __init__(self, path=ASSETS / "dem_coarse.npz"):
        d = np.load(path)
        self.layers = [(d[k], float(d[f"{k}_left"]), float(d[f"{k}_top"]), float(d[f"{k}_res"]))
                       for k in ("near", "far")]

    def heights_xy(self, x, y):
        x, y = np.atleast_1d(np.asarray(x, float)), np.atleast_1d(np.asarray(y, float))
        h = np.full(x.shape, np.nan)
        for grid, left, top, res in self.layers:
            miss = np.isnan(h)
            if not miss.any():
                break
            h[miss] = _bilinear(grid, (x[miss] - left) / res - 0.5, (top - y[miss]) / res - 0.5)
        return h

    def resolution_at(self, lat, lon):
        """Grid spacing (m) of the finest layer covering the point, or None."""
        if lat > self.MIN_LAT:
            return None
        x, y = polar_xy(lat, lon)
        for grid, left, top, res in self.layers:
            if not np.isnan(_bilinear(grid, np.atleast_1d((x - left) / res - 0.5),
                                      np.atleast_1d((top - y) / res - 0.5))[0]):
                return res
        return None

    def horizon_mask(self, lat, lon, obs_h=2.0, max_d=150_000, step=240.0):
        """Same method as the precomputed masks, on the coarse terrain. None if no terrain."""
        if self.resolution_at(lat, lon) is None:
            return None, None
        x0, y0 = polar_xy(lat, lon)
        h0 = float(self.heights_xy(x0, y0)[0]) + obs_h
        az = np.arange(0, 360, 1.0)
        d = np.arange(2 * step, max_d + step, step)
        AZ, D = np.meshgrid(az, d, indexing="ij")
        lat2, lon2 = destination(lat, lon, AZ, D)
        x, y = polar_xy(lat2.ravel(), lon2.ravel())
        h = self.heights_xy(x, y).reshape(AZ.shape)
        ang = np.degrees(np.arctan2(h - h0 - D**2 / (2 * R_MOON), D))
        ang = np.where(np.isnan(ang), -np.inf, ang)
        hz = ang.max(axis=1)
        hz = np.where(np.isfinite(hz), hz, 0.0)            # direction leaves the terrain model
        return pd.DataFrame({"az": az, "horizon": hz}), h0

    def patch(self, lat, lon, half=10_000, step=100):
        """20 x 20 km terrain patch in the same format as load_terrain3d. None if no terrain."""
        if self.resolution_at(lat, lon) is None:
            return None
        g = np.arange(-half, half + step, step, dtype=float)
        E, N = np.meshgrid(g, g)
        lam = np.radians(lon)
        x0, y0 = polar_xy(lat, lon)
        dx = E * np.cos(lam) + N * np.sin(lam)
        dy = -E * np.sin(lam) + N * np.cos(lam)
        h = self.heights_xy((x0 + dx).ravel(), (y0 + dy).ravel()).reshape(E.shape)
        z = h - (E**2 + N**2) / (2 * R_MOON)
        return {"east": g, "north": g, "z": z, "h0": float(self.heights_xy(x0, y0)[0])}


# ---------------------------------------------------------------- cast shadows for the 3D view
def shadow_map(patch, coarse, lat, lon, sun_az, sun_alt, every=2,
               near_step=100.0, far_step=500.0, far_max=100_000.0):
    """Lit (True) / shadowed (False) for the 3D terrain patch at one Sun position.

    Works in the landing site's local frame: patch["z"] already includes the drop from lunar
    curvature, so a point is lit when no terrain rises above the straight ray toward the Sun.
    Inside the patch the ray uses the 100 m patch; beyond it, the coarse terrain (240 m)
    out to `far_max`, so distant ridges can still cast shadows. Returns a grid at every
    `every`-th patch point plus its east/north coordinates.
    """
    e, n, z = patch["east"], patch["north"], patch["z"]
    step = e[1] - e[0]
    E, N = np.meshgrid(e[::every], n[::every])
    Z = z[::every, ::every]
    ux, uy = np.sin(np.radians(sun_az)), np.cos(np.radians(sun_az))
    slope = np.tan(np.radians(sun_alt + SUN_RADIUS_DEG))      # top of the solar disc

    t = np.concatenate([np.arange(near_step, 2 * e.max() * 1.5, near_step),
                        np.arange(2 * e.max() * 1.5, far_max + far_step, far_step)])
    lit = np.ones(E.shape, bool)
    for tk in t:
        qe, qn = E + tk * ux, N + tk * uy
        inside = (np.abs(qe) <= e.max()) & (np.abs(qn) <= n.max())
        hq = np.full(E.shape, np.nan)
        if inside.any():
            ci, ri = (qe[inside] - e[0]) / step, (qn[inside] - n[0]) / step
            hq[inside] = _bilinear_float(z, ci, ri)
        out = ~inside & lit
        if out.any() and coarse is not None:
            dist = np.hypot(qe[out], qn[out])
            la, lo = destination(lat, lon, np.degrees(np.arctan2(qe[out], qn[out])), dist)
            x, y = polar_xy(la, lo)
            hq[out] = coarse.heights_xy(x, y) - dist**2 / (2 * R_MOON)
        lit &= ~(hq > Z + tk * slope)
    return E, N, lit


def _bilinear_float(grid, col, row):
    out = np.full(np.shape(row), np.nan)
    r0, c0 = np.floor(row), np.floor(col)
    ok = (r0 >= 0) & (c0 >= 0) & (r0 < grid.shape[0] - 1) & (c0 < grid.shape[1] - 1)
    r, c = r0[ok].astype(int), c0[ok].astype(int)
    fr, fc = row[ok] - r, col[ok] - c
    out[ok] = (grid[r, c] * (1 - fr) * (1 - fc) + grid[r, c + 1] * (1 - fr) * fc
               + grid[r + 1, c] * fr * (1 - fc) + grid[r + 1, c + 1] * fr * fc)
    return out


# ---------------------------------------------------------------- power and battery
SOLAR_CONSTANT = 1361.0          # W/m² at 1 AU


def disc_fraction(margin, radius=SUN_RADIUS_DEG):
    """Visible fraction of the solar disc, given how far its top clears the horizon (deg).
    Treats the horizon as a straight edge across the disc (circular segment area)."""
    h = np.clip((np.asarray(margin, float) - radius) / radius, -1, 1)   # centre height in radii
    theta = 2 * np.arccos(h)                                           # angle of the hidden segment
    return 1 - (theta - np.sin(theta)) / (2 * np.pi)


def power_budget(df, step_hours, area_m2=4.0, efficiency=0.30, load_w=150.0):
    """Output of a vertical, Sun-tracking panel (the usual layout for polar landers) and the
    battery needed to keep a constant load running, from the energy balance over time:
    the battery must cover the deepest drop in cumulative (generation - load)."""
    frac = disc_fraction(df["sun_margin"])
    cos_alt = np.cos(np.radians(df["sun_alt"].clip(-90, 90)))
    p = SOLAR_CONSTANT * efficiency * area_m2 * cos_alt * frac
    energy = np.concatenate([[0.0], np.cumsum((p - load_w).to_numpy() * step_hours)])   # Wh
    drawdown = np.maximum.accumulate(energy) - energy
    return {
        "power": pd.Series(p.to_numpy(), index=df.index),
        "mean_w": float(p.mean()),
        "kwh_per_day": float(p.mean()) * 24 / 1000,
        "battery_kwh": float(drawdown.max()) / 1000,
        "deficit_h": longest_run_hours((p < load_w).to_numpy(), step_hours),
    }


def load_illum3d(site_id):
    """NASA long-term Sun/Earth visibility on the 3D terrain grid (None if missing)."""
    path = ASSETS / "illum3d" / f"{site_id}.npz"
    if not path.exists():
        return None
    d = np.load(path)
    return {"sun": d["sun"], "earth": d["earth"]}