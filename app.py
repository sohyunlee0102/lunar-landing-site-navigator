import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import lunar_core as lc

SUN = "#C7811E"
EARTH = "#2F6FB5"
SUN_LIGHT = "#E6C48E"
EARTH_LIGHT = "#A7C0E0"
TERRAIN = "#7D766C"
ALT_OFFSET = 10          # polar plot radius = altitude + 10, so -10° sits at the centre
ALT_MAX = 15
FLAT_MASK = pd.DataFrame({"az": np.arange(360.0), "horizon": np.zeros(360)})
SCAN_DAYS = 365
SCAN_STEP = 2            # hours
VERT_EXAG = 2.0          # vertical exaggeration of the 3D terrain view
CUSTOM_LABEL = "Custom coordinates…"

st.set_page_config(page_title="Lunar Landing Site Navigator", page_icon="🌗", layout="wide")


@st.cache_resource
def get_ephemeris():
    return lc.Ephemeris()


@st.cache_data
def get_sites():
    return lc.load_sites()


@st.cache_data
def get_mask(site_id):
    return lc.load_mask(site_id)


@st.cache_data
def get_offsets(site_id):
    return lc.load_offset_masks(site_id)


@st.cache_data
def get_terrain3d(site_id):
    return lc.load_terrain3d(site_id)


@st.cache_data
def get_illum3d(site_id):
    return lc.load_illum3d(site_id)


@st.cache_resource
def get_coarse_terrain():
    try:
        return lc.CoarseTerrain()
    except FileNotFoundError:
        return None


@st.cache_data(show_spinner="Building the horizon for your coordinates…")
def get_custom_mask(lat, lon):
    ct = get_coarse_terrain()
    if ct is None:
        return None, None
    mask, _ = ct.horizon_mask(lat, lon)
    return mask, ct.resolution_at(lat, lon)


@st.cache_data
def get_custom_patch(lat, lon):
    ct = get_coarse_terrain()
    return None if ct is None else ct.patch(lat, lon)


@st.cache_data(show_spinner="Casting shadows…")
def get_shadow(site_key, _patch, lat, lon, sun_az, sun_alt):
    """Cast-shadow grid for the 3D view; `site_key` identifies the patch for caching."""
    return lc.shadow_map(_patch, get_coarse_terrain(), lat, lon, sun_az, sun_alt)


@st.cache_data(show_spinner="Computing Sun and Earth positions…")
def get_track(lat, lon, start, days, step):
    return get_ephemeris().sky_track(lat, lon, start, days, step)


@st.cache_data(show_spinner="Scanning a year of landing dates for every site…")
def get_scan(start, use_terrain):
    rows = {}
    for s in get_sites().itertuples():
        if s.lat > -60:                      # the calendar is for south polar sites
            continue
        track = get_track(float(s.lat), float(s.lon), start, SCAN_DAYS + 7, SCAN_STEP)
        mask = get_mask(s.id) if use_terrain else FLAT_MASK
        rows[s.name] = lc.landing_scan(lc.visibility(track, mask), SCAN_STEP)
    return pd.DataFrame(rows).T.iloc[:, :SCAN_DAYS]


def fmt_hours(h):
    if h is None:
        return "> period"
    return f"{h / 24:.1f} days" if h >= 48 else f"{h:.0f} h"


def sky_dome(mask, df, title, show_terrain, now=None):
    """Polar sky plot. Polar sites: horizon-zoomed (centre = -10°, outward = higher).
    Sites where the Sun or Earth climbs above 30°: standard sky chart (centre = zenith)."""
    peak = max(df["sun_alt"].max(), df["earth_alt"].max())
    full_sky = peak > 30

    if full_sky:
        r_max = 100                                   # 90° at the centre, 0° at r=90, -10° at r=100

        def to_r(alt):
            return np.clip(90 - np.asarray(alt, float), 0, r_max)
        ticks = [0, 30, 60, 90, 100]
        ticktext = ["90°", "60°", "30°", "0°", "-10°"]
    else:
        alt_max = int(min(90, max(ALT_MAX, 5 * np.ceil((peak + 2) / 5))))
        r_max = alt_max + ALT_OFFSET

        def to_r(alt):
            return np.clip(np.asarray(alt, float) + ALT_OFFSET, 0, r_max)
        ticks = list(range(0, r_max + 1, 5 if alt_max <= 30 else 10))
        ticktext = [f"{t - ALT_OFFSET}°" for t in ticks]

    fig = go.Figure()
    if show_terrain:
        az = np.append(mask["az"].to_numpy(), mask["az"].iloc[0])
        hz_r = to_r(np.append(mask["horizon"].to_numpy(), mask["horizon"].iloc[0]))
        if full_sky:
            # ground lies between the terrain horizon and the outer edge
            theta = np.concatenate([az, az[::-1]])
            r = np.concatenate([hz_r, np.full(len(az), r_max)])
        else:
            theta, r = az, hz_r
        fig.add_trace(go.Scatterpolar(
            theta=theta, r=r, mode="lines", fill="toself", name="Terrain",
            line=dict(color=TERRAIN, width=1.5), fillcolor="rgba(125,118,108,0.35)", hoverinfo="skip"))
    fig.add_trace(go.Scatterpolar(
        theta=np.arange(0, 361, 5), r=np.full(73, float(to_r(0))), mode="lines",
        name="0° (flat horizon)", line=dict(color=TERRAIN, width=1, dash="dot"), hoverinfo="skip"))

    styles = {"sun": (SUN, SUN_LIGHT), "earth": (EARTH, EARTH_LIGHT)}
    for body, (dark, light) in styles.items():
        alt = df[f"{body}_alt"]
        keep = (alt >= -10) & (alt <= 90)
        r = pd.Series(to_r(alt), index=df.index)
        vis = df[f"{body}_vis"]
        label = body.capitalize()
        # draw blocked first so visible points sit on top
        for sel_vis, name, c in ((~vis, f"{label} blocked", light), (vis, f"{label} visible", dark)):
            sel = keep & sel_vis
            fig.add_trace(go.Scatterpolar(
                theta=df.loc[sel, f"{body}_az"], r=r[sel], mode="markers", name=name,
                marker=dict(size=4, color=c),
                customdata=df.index[sel].strftime("%Y-%m-%d %H:%M"),
                hovertemplate="%{customdata} UTC<br>az %{theta:.1f}°<extra>" + name + "</extra>"))

    if now is not None:
        for body, color, symbol, label in (("sun", SUN, "star", "Sun at chosen time"),
                                           ("earth", EARTH, "circle", "Earth at chosen time")):
            fig.add_trace(go.Scatterpolar(
                theta=[now[f"{body}_az"]], r=[float(to_r(now[f"{body}_alt"]))], mode="markers", name=label,
                marker=dict(size=20, color=color, symbol=symbol, line=dict(color="white", width=2)),
                hovertemplate=f"{label}<br>elevation {now[f'{body}_alt']:.2f}°<extra></extra>"))

    fig.update_layout(
        title=dict(text=title + (", full sky" if full_sky else ""), x=0.5),
        height=460, margin=dict(l=30, r=30, t=60, b=30),
        legend=dict(orientation="h", y=-0.08),
        polar=dict(
            angularaxis=dict(rotation=90, direction="clockwise",
                             tickvals=[0, 90, 180, 270], ticktext=["N", "E", "S", "W"]),
            radialaxis=dict(range=[0, r_max], tickvals=ticks, ticktext=ticktext,
                            angle=-45, tickangle=0, tickfont=dict(size=10), showline=False),
        ),
    )
    return fig


def _wrap(az):
    """Azimuth to -180..180 so north sits in the middle of the panorama."""
    return (np.asarray(az, float) + 180) % 360 - 180


def _status(row):
    sun = "visible" if row["sun_vis"] else "hidden"
    earth = "visible" if row["earth_vis"] else "hidden"
    return (f"<b>{row.name:%Y-%m-%d %H:%M} UTC</b>   Sun {row['sun_alt']:+.1f}° ({sun})   "
            f"Earth {row['earth_alt']:+.1f}° ({earth})")


def panorama(mask, df, title, show_terrain, now_idx=0, max_frames=240):
    """360° horizon panorama, north in the middle, with a play button that animates the
    Sun and Earth across the selected period."""
    az_h = np.arange(-180, 181, 1.0)
    hz = lc.horizon_at(mask, az_h % 360) if show_terrain else np.zeros_like(az_h)
    lows = [hz.min(), df["sun_alt"].min(), df["earth_alt"].min()]
    y_low = max(-10.0, min(-3.0, float(np.floor(min(lows) - 1))))
    peak = max(df["sun_alt"].max(), df["earth_alt"].max())
    y_high = float(min(92, max(10, np.ceil(peak + 3))))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[-180, 180], y=[y_low, y_low], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=az_h, y=hz, mode="lines", fill="tonexty", name="Terrain",
                             line=dict(color=TERRAIN, width=1.5), fillcolor="rgba(125,118,108,0.45)",
                             hovertemplate="az %{x:.0f}°<br>horizon %{y:.2f}°<extra></extra>"))
    fig.add_trace(go.Scatter(x=[-180, 180], y=[0, 0], mode="lines", name="0° (flat horizon)",
                             line=dict(color=TERRAIN, width=1, dash="dot"), hoverinfo="skip"))

    styles = {"sun": (SUN, SUN_LIGHT), "earth": (EARTH, EARTH_LIGHT)}
    for body, (dark, light) in styles.items():
        vis = df[f"{body}_vis"]
        keep = df[f"{body}_alt"] >= y_low
        label = body.capitalize()
        for sel_vis, name, c in ((~vis, f"{label} blocked", light), (vis, f"{label} visible", dark)):
            sel = keep & sel_vis
            fig.add_trace(go.Scatter(
                x=_wrap(df.loc[sel, f"{body}_az"]), y=df.loc[sel, f"{body}_alt"], mode="markers",
                name=name, marker=dict(size=3, color=c),
                customdata=df.index[sel].strftime("%Y-%m-%d %H:%M"),
                hovertemplate="%{customdata} UTC<br>az %{x:.1f}°, alt %{y:.2f}°<extra>" + name + "</extra>"))

    row = df.iloc[now_idx]
    moving = len(fig.data)
    fig.add_trace(go.Scatter(x=[_wrap(row["sun_az"])], y=[row["sun_alt"]], mode="markers", name="Sun now",
                             marker=dict(size=22, color=SUN, symbol="star", line=dict(color="white", width=2))))
    fig.add_trace(go.Scatter(x=[_wrap(row["earth_az"])], y=[row["earth_alt"]], mode="markers", name="Earth now",
                             marker=dict(size=18, color=EARTH, line=dict(color="white", width=2))))

    # status line as a text trace (data updates animate smoothly; layout updates would not)
    text_y = y_high - 0.06 * (y_high - y_low)
    fig.add_trace(go.Scatter(x=[-176], y=[text_y], mode="text", text=[_status(row)],
                             textposition="middle right", textfont=dict(size=12, color="#1E2329"),
                             showlegend=False, hoverinfo="skip"))

    picks = np.unique(np.linspace(0, len(df) - 1, min(len(df), max_frames)).astype(int))
    fig.frames = [go.Frame(
        name=str(i), traces=[moving, moving + 1, moving + 2],
        data=[go.Scatter(x=[_wrap(df["sun_az"].iloc[i])], y=[df["sun_alt"].iloc[i]]),
              go.Scatter(x=[_wrap(df["earth_az"].iloc[i])], y=[df["earth_alt"].iloc[i]]),
              go.Scatter(text=[_status(df.iloc[i])])])
        for i in picks]

    fig.update_layout(
        title=dict(text=title, x=0.5), height=400, margin=dict(l=40, r=20, t=70, b=40),
        legend=dict(orientation="h", y=-0.22),
        xaxis=dict(range=[-180, 180], tickvals=list(range(-180, 181, 45)),
                   ticktext=["S", "SW", "W", "NW", "N", "NE", "E", "SE", "S"], showgrid=False),
        yaxis=dict(range=[y_low, y_high], title="elevation (°)", zeroline=False),
        updatemenus=[dict(
            type="buttons", direction="left", x=1.0, y=1.02, xanchor="right", yanchor="bottom",
            showactive=False, pad=dict(t=0, r=0),
            buttons=[dict(label="▶ Play", method="animate",
                          args=[None, dict(frame=dict(duration=80, redraw=False),
                                           transition=dict(duration=0), fromcurrent=True, mode="immediate")]),
                     dict(label="❚❚ Pause", method="animate",
                          args=[[None], dict(frame=dict(duration=0, redraw=False),
                                             transition=dict(duration=0), mode="immediate")])])])
    return fig


def landing_calendar(scan):
    """Sites x landing dates. Grey: no 6.5-day sunlit stay. Colour: Earth contact during stay."""
    days_ok = scan.notna().sum(axis=1)
    ylabels = [f"{n}  ({d} days)" for n, d in zip(scan.index, days_ok)]
    x = pd.DatetimeIndex(scan.columns).tz_localize(None)
    fig = go.Figure(go.Heatmap(
        z=scan.to_numpy(), x=x, y=ylabels, zmin=0, zmax=100,
        colorscale=[[0, "#F3E3C3"], [1, EARTH]], ygap=3,
        colorbar=dict(title=dict(text="Earth in view<br>during stay (%)"), thickness=12),
        hovertemplate="%{y}<br>Land on %{x|%Y-%m-%d}<br>Earth in view %{z:.0f}%<extra></extra>"))
    fig.update_layout(
        height=90 + 48 * len(scan), plot_bgcolor="#D9D6D0",
        margin=dict(l=10, r=10, t=10, b=30),
        yaxis=dict(autorange="reversed"), xaxis=dict(showgrid=False))
    return fig


def sensitivity_map(sens, key, label):
    """Points around the site, coloured by the chosen metric. Dotted ring = 100 m."""
    t = np.linspace(0, 2 * np.pi, 120)
    vals = sens[key].to_numpy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=100 * np.sin(t), y=100 * np.cos(t), mode="lines",
                             line=dict(color=TERRAIN, dash="dot"), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=sens["east_m"], y=sens["north_m"], mode="markers+text",
        marker=dict(size=36, color=vals, cmin=0, cmax=100,
                    colorscale=[[0, "#F3E3C3"], [1, EARTH]], line=dict(color="white", width=1)),
        text=[f"{v:.0f}" for v in vals],
        textfont=dict(size=11, color=["white" if v > 60 else "#1E2329" for v in vals]),
        customdata=sens["height_m"],
        hovertemplate="%{x:.0f} m east, %{y:.0f} m north<br>" + label
                      + " %{marker.color:.1f}%<br>elevation %{customdata:.0f} m<extra></extra>",
        showlegend=False))
    axis = dict(range=[-270, 270], zeroline=False, showgrid=False, ticksuffix=" m")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                      xaxis=dict(axis, title="east"),
                      yaxis=dict(axis, title="north", scaleanchor="x"))
    return fig


def terrain_3d(t, now, title, shadow=None, overlay=None):
    """Local terrain with cast shadows for the chosen time (or a NASA long-term map as colour),
    and lines to the Sun and Earth."""
    if overlay is not None:
        values, label, scale = overlay
        e, n = t["east"] / 1000, t["north"] / 1000
        z = (t["z"] - t["h0"]) / 1000
        surface = dict(surfacecolor=100 * values, cmin=0, cmax=100, colorscale=scale,
                       colorbar=dict(title=dict(text=label), thickness=12, len=0.6, ticksuffix="%"))
    elif shadow is not None:
        E, N, lit = shadow
        e, n = E[0] / 1000, N[:, 0] / 1000
        every = int(round((E[0, 1] - E[0, 0]) / (t["east"][1] - t["east"][0])))
        z = (t["z"][::every, ::every] - t["h0"]) / 1000
        zn = (z - np.nanmin(z)) / max(float(np.nanmax(z) - np.nanmin(z)), 1e-6)
        colour = 0.35 * zn + 0.65 * lit           # shadows fall in 0–0.35, sunlit ground in 0.65–1
        surface = dict(surfacecolor=colour, cmin=0, cmax=1,
                       colorscale=[[0, "#1E1C1A"], [0.35, "#56524D"], [0.65, "#BFB9B0"], [1, "#F6F3EE"]])
    else:
        e, n = t["east"] / 1000, t["north"] / 1000
        z = (t["z"] - t["h0"]) / 1000
        surface = dict(colorscale=[[0, "#4A4743"], [1, "#F2EFEA"]])

    def unit(body):
        az, alt = np.radians(now[f"{body}_az"]), np.radians(now[f"{body}_alt"])
        return np.array([np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)])

    sun_dir = unit("sun")
    light = 1e5 * np.array([sun_dir[0], sun_dir[1], max(sun_dir[2], 0.02)])
    fig = go.Figure(go.Surface(
        x=e, y=n, z=z, showscale=overlay is not None, **surface,
        lighting=(dict(ambient=0.95, diffuse=0.15, roughness=1.0, specular=0.0) if overlay is not None
            else dict(ambient=0.7, diffuse=0.4, roughness=0.9, specular=0.03)),
        lightposition=dict(x=light[0], y=light[1], z=light[2]),
        hovertemplate="%{x:.1f} km east, %{y:.1f} km north<br>%{z:+.2f} km vs site<extra></extra>"))
    length = 7.0                                         # km
    base = np.array([0.0, 0.0, 0.003])
    for body, color, light_c, label in (("sun", SUN, SUN_LIGHT, "Sun"), ("earth", EARTH, EARTH_LIGHT, "Earth")):
        tip = base + length * unit(body)
        visible = now[f"{body}_margin"] > 0
        c = color if visible else light_c
        xs, ys, zs = [base[0], tip[0]], [base[1], tip[1]], [base[2], tip[2]]
        # white halo underneath so the line stands out on any terrain colour
        fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines",
                                   line=dict(color="white", width=14), hoverinfo="skip"))
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs, mode="lines+text",
            line=dict(color=c, width=8, dash="solid" if visible else "dash"),
            text=["", f"<b>{label} ({'visible' if visible else 'hidden'})</b>"], textposition="top center",
            textfont=dict(color=c, size=13), hoverinfo="skip"))
    fig.add_trace(go.Scatter3d(x=[0], y=[0], z=[0.003], mode="markers",
                               marker=dict(size=7, color="#C0392B", line=dict(color="white", width=3)),
                               hoverinfo="skip"))
    z_range = float(np.nanmax(z) - np.nanmin(z))
    span = float(e.max() - e.min())
    fig.update_layout(
        title=dict(text=title, x=0.5), height=460, margin=dict(l=0, r=0, t=50, b=0), showlegend=False,
        scene=dict(
            xaxis=dict(title="east (km)"), yaxis=dict(title="north (km)"), zaxis=dict(title="km"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=max(z_range / span * VERT_EXAG, 0.05)),
            camera=dict(eye=dict(x=-0.4, y=-0.9, z=1.9) if overlay is not None
                        else dict(x=-1.3, y=-1.3, z=0.7))))
    return fig


def power_chart(results, load):
    fig = go.Figure()
    for (name, res), color in zip(results.items(), (SUN, EARTH)):
        p = res["power"]["power"]
        fig.add_trace(go.Scatter(x=p.index.tz_localize(None), y=p, name=name, mode="lines",
                                 line=dict(color=color, width=1.5)))
    fig.add_hline(y=load, line=dict(color=TERRAIN, dash="dot"),
                  annotation_text=f"load {load:.0f} W", annotation_position="top left")
    fig.update_layout(height=300, margin=dict(l=40, r=20, t=30, b=30), yaxis_title="panel output (W)",
                      legend=dict(orientation="h", y=1.12))
    return fig


def timeline(dfa, dfb, name_a, name_b, when=None):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=(name_a, name_b))
    for row, df in ((1, dfa), (2, dfb)):
        x = df.index.tz_localize(None)
        for body, color, label in (("sun", SUN, "Sun"), ("earth", EARTH, "Earth")):
            fig.add_trace(go.Scatter(
                x=x, y=df[f"{body}_margin"], name=f"{label} clearance above horizon",
                line=dict(color=color, width=1.5), showlegend=(row == 1)), row=row, col=1)
        fig.add_hline(y=0, line=dict(color=TERRAIN, dash="dot"), row=row, col=1)
    if when is not None:
        fig.add_vline(x=when, line=dict(color="#1E2329", width=1.5))
    fig.update_yaxes(title_text="degrees")
    fig.update_layout(height=520, margin=dict(l=40, r=20, t=50, b=30),
                      legend=dict(orientation="h", y=1.08))
    return fig


# ---------------------------------------------------------------- inputs
sites = get_sites()
names = sites["name"].tolist()
if "start" not in st.session_state:
    st.session_state["start"] = dt.date(2027, 1, 1)


def go_to_landing(date_text):
    st.session_state["start"] = dt.date.fromisoformat(date_text)


with st.sidebar:
    st.header("Scenario")
    default_a = names.index("Malapert Massif") if "Malapert Massif" in names else 0
    default_b = names.index("Haworth") if "Haworth" in names else min(1, len(names) - 1)
    options = names + [CUSTOM_LABEL]
    name_a = st.selectbox("Site A", options, index=default_a)
    name_b = st.selectbox("Site B", options, index=default_b)
    c_lat = c_lon = None
    if CUSTOM_LABEL in (name_a, name_b):
        c_lat = st.number_input("Custom latitude (°)", min_value=-89.99, max_value=90.0,
                                value=-89.0, step=0.1, format="%.4f", key="c_lat")
        c_lon = st.number_input("Custom longitude (°E)", min_value=-180.0, max_value=360.0,
                                value=0.0, step=0.1, format="%.4f", key="c_lon")
        st.caption("Custom sites use coarse terrain: 240 m south of 80°S, 960 m to 60°S, "
                   "and a smooth sphere further north.")
    start = st.date_input("Start date (UTC)", key="start",
                          min_value=dt.date(1950, 1, 1), max_value=dt.date(2049, 1, 1))
    for n in dict.fromkeys((name_a, name_b)):
        if n == CUSTOM_LABEL:
            continue
        landed = sites.loc[sites["name"] == n, "landed"].iloc[0]
        if isinstance(landed, str) and landed:
            st.button(f"Go to {n.split(' (')[0]} landing date ({landed})",
                      on_click=go_to_landing, args=(landed,), use_container_width=True)
    days = st.slider("Period (days)", 7, 365, 30)
    step = 1 if days <= 60 else 3
    use_terrain = st.checkbox("Include real terrain (LOLA)", value=True)
    with st.expander("Power assumptions"):
        panel_m2 = st.number_input("Solar panel area (m²)", 0.5, 100.0, 4.0, 0.5)
        panel_eff = st.slider("Panel efficiency (%)", 10, 40, 30) / 100
        load_w = st.number_input("Constant load (W)", 10.0, 10000.0, 150.0, 10.0)
    st.caption(f"Time step: {step} h. Horizon masks assume a 2 m high panel or antenna. "
               "Sites: Artemis III candidate regions and past landings near the south pole.")


# ---------------------------------------------------------------- site helpers
def site_record(name):
    if name == CUSTOM_LABEL:
        _, res = get_custom_mask(c_lat, c_lon)
        terrain = f"{res:.0f} m coarse terrain" if res else "no terrain data, smooth sphere"
        return pd.Series({"id": lc.CUSTOM_ID, "name": name, "lat": c_lat, "lon": c_lon,
                          "landed": None, "group": f"Custom site · {terrain}"})
    return sites[sites["name"] == name].iloc[0]


def site_mask(s):
    if s["id"] == lc.CUSTOM_ID:
        mask, _ = get_custom_mask(s["lat"], s["lon"])
        return FLAT_MASK if mask is None else mask
    return get_mask(s["id"])


def site_terrain3d(s):
    if s["id"] == lc.CUSTOM_ID:
        return get_custom_patch(s["lat"], s["lon"])
    return get_terrain3d(s["id"])


def custom_uncertainty(track, lat, lon, dist=250):
    """Sunlight and Earth-in-view at the custom point and 4 points `dist` m away.
    A wide spread means coarse terrain cannot be trusted at this spot."""
    vals = []
    for az in (None, 0, 90, 180, 270):
        la, lo = (lat, lon) if az is None else lc.destination(lat, lon, az, dist)
        mask, _ = get_custom_mask(round(float(la), 6), round(float(lo), 6))
        if mask is None:
            return None
        v = lc.visibility(track, mask)
        vals.append((100 * v["sun_vis"].mean(), 100 * v["earth_vis"].mean()))
    a = np.array(vals)
    return {"sun": (a[:, 0].min(), a[:, 0].max()), "earth": (a[:, 1].min(), a[:, 1].max())}


# ---------------------------------------------------------------- compute
results = {}
for name in dict.fromkeys((name_a, name_b)):
    s = site_record(name)
    track = get_track(float(s["lat"]), float(s["lon"]), start, days, step)
    terrain_df = lc.visibility(track, site_mask(s))
    flat_df = lc.visibility(track, FLAT_MASK)
    df = terrain_df if use_terrain else flat_df
    results[name] = {
        "site": s,
        "track": track,
        "df": df,
        "m": lc.summarize(df, step),
        "m_terrain": lc.summarize(terrain_df, step),
        "m_flat": lc.summarize(flat_df, step),
        "power": lc.power_budget(df, step, panel_m2, panel_eff, load_w),
    }

# ---------------------------------------------------------------- page
st.title("Lunar Landing Site Navigator")
st.write("Compare power (sunlight) and direct-to-Earth communication at lunar south pole "
         "landing sites, using real LOLA terrain. Change the dates or sites and every number updates.")
with st.expander("New to this? Why the lunar south pole is hard", expanded=False):
    st.markdown("""
The Moon's axis is tilted only 1.5°, so at the south pole the Sun never climbs high. It circles
the horizon once every 29.5 days, hugging it within a few degrees. A hill one degree high can
block it, so a few hundred metres can decide between sunlight and darkness.

Earth barely moves in the lunar sky, but a monthly wobble (libration) lifts it a few degrees above
the horizon and then drops it below. When Earth is hidden, a lander cannot talk home directly.

Real terrain cuts both ways. Crater floors can stay dark for years, while high ridges see past the
flat horizon and keep both the Sun and Earth in view for longer. That is why landing sites and dates
have to be checked together, with real topography.
""")
if not use_terrain:
    st.info("Terrain is off: every site is treated as a smooth sphere. "
            "Turn it back on to see what the real horizon blocks.")

st.subheader("Landing calendar: which site works on which day?")
st.caption(f"Each cell is a landing date over {SCAN_DAYS} days from the start date. "
           "Coloured: landing that day gives 6.5 days of continuous sunlight, shaded by how much "
           "of the stay Earth is in view. Grey: no landing time that day stays sunlit. "
           "The number after each site is how many days work.")
scan = get_scan(start, use_terrain)
st.plotly_chart(landing_calendar(scan), use_container_width=True)
no_site = int(scan.isna().all(axis=0).sum())
st.caption(f"Days when no candidate site works: {no_site} of {SCAN_DAYS}. "
           "Having several sites is what keeps every launch date usable.")

st.subheader(f"Compare two sites: {name_a} vs {name_b}")
rows = [
    ("Sunlight", "sunlight_pct", "{:.1f}%"),
    ("Highest solar elevation", "sun_elev_max", "{:.2f}°"),
    ("Mean solar elevation while sunlit", "sun_elev_mean_up", "{:.2f}°"),
    ("Earth in view", "earth_pct", "{:.1f}%"),
    ("Sun and Earth together", "ops_pct", "{:.1f}%"),
    ("Longest darkness", "longest_dark_h", None),
    ("Longest communication blackout", "longest_blackout_h", None),
    ("Longest continuous sunlight", "longest_sun_h", None),
]
table = {}
for name, res in results.items():
    m = res["m"]
    col = [("—" if m[key] is None else fmt.format(m[key])) if fmt else fmt_hours(m[key])
           for _, key, fmt in rows]
    col.append(f"{len(m['mission_windows'])} window(s)")
    table[name] = col
labels = [label for label, _, _ in rows] + ["Sunlit stretches ≥ 6.5 days"]
st.dataframe(pd.DataFrame(table, index=labels), use_container_width=True)

st.markdown("**What the terrain changes** (smooth sphere → real terrain)")
effect = []
for name, res in results.items():
    mf, mt = res["m_flat"], res["m_terrain"]
    effect.append({
        "Site": name,
        "Sunlight": f"{mf['sunlight_pct']:.0f}% → {mt['sunlight_pct']:.0f}%",
        "Earth in view": f"{mf['earth_pct']:.0f}% → {mt['earth_pct']:.0f}%",
        "Sun and Earth together": f"{mf['ops_pct']:.0f}% → {mt['ops_pct']:.0f}%",
        "Longest darkness": f"{fmt_hours(mf['longest_dark_h'])} → {fmt_hours(mt['longest_dark_h'])}",
    })
st.dataframe(pd.DataFrame(effect).set_index("Site"), use_container_width=True)
if use_terrain:
    for name, res in results.items():
        s = res["site"]
        if s["id"] != lc.CUSTOM_ID:
            continue
        year_track = get_track(float(s["lat"]), float(s["lon"]), start, 365, 2)
        u = custom_uncertainty(year_track, s["lat"], s["lon"])
        if u is None:
            continue
        spread = max(u["sun"][1] - u["sun"][0], u["earth"][1] - u["earth"][0])
        text = (f"Moving the custom point 250 m in any direction gives sunlight "
                f"{u['sun'][0]:.0f}–{u['sun'][1]:.0f}% and Earth in view "
                f"{u['earth'][0]:.0f}–{u['earth'][1]:.0f}% over the year from the start date.")
        if spread > 15:
            st.warning(f"**Custom site: position-sensitive terrain.** {text} Small ridges below "
                       "the 240 m resolution of the coarse terrain may change these results.")
        else:
            st.caption(f"Custom site: results are stable nearby. {text}")

st.subheader("Power and battery")
st.caption(f"A vertical solar panel turning to face the Sun (the usual layout at the poles), "
           f"{panel_m2:g} m² at {panel_eff:.0%} efficiency, powering a constant {load_w:.0f} W load. "
           "Output counts only the part of the solar disc above the terrain. The battery must cover the "
           "deepest dip in stored energy over the period, starting full. Change the numbers under "
           "'Power assumptions' in the sidebar.")
power_rows = {}
for name, res in results.items():
    pb = res["power"]
    power_rows[name] = [
        f"{pb['mean_w']:.0f} W",
        f"{pb['kwh_per_day']:.1f} kWh",
        f"{pb['mean_w'] / load_w:.1f}×",
        f"{pb['battery_kwh']:.1f} kWh",
        fmt_hours(pb["deficit_h"]),
    ]
st.dataframe(pd.DataFrame(power_rows, index=[
    "Average panel output", "Energy per day", "Average output ÷ load",
    "Battery needed to keep the load running", "Longest stretch with output below load",
]), use_container_width=True)
st.plotly_chart(power_chart(results, load_w), use_container_width=True)
st.subheader("Sun and Earth at a chosen moment")
st.caption("Drag the time. The large star and dot mark where the Sun and Earth are right then; "
           "the small dots trace their paths over the whole period. 'Above terrain' is how far the "
           "top of each disc clears the local horizon: negative means hidden.")
t0 = dt.datetime.combine(start, dt.time())
when = st.slider("Time (UTC)", min_value=t0, max_value=t0 + dt.timedelta(days=days),
                 value=t0, step=dt.timedelta(hours=step), format="YYYY-MM-DD HH:mm")
idx = int(round((when - t0).total_seconds() / 3600 / step))

cols = st.columns(2)
for k, (col, name) in enumerate(zip(cols, (name_a, name_b))):
    res = results[name]
    s = res["site"]
    now = lc.moment(res["df"], min(idx, len(res["df"]) - 1), step)
    mask = site_mask(s) if use_terrain else FLAT_MASK
    with col:
        st.markdown(f"**{name}**  ·  {s['lat']:.4f}°, {s['lon']:.4f}°  ·  {s['group']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Solar elevation", f"{now['sun_alt']:.2f}°")
        c2.metric("Sun above terrain", f"{now['sun_margin']:+.2f}°")
        c3.metric("Sunset in" if now["sun_now"] else "Sunrise in", fmt_hours(now["sun_change_h"]))
        c1.metric("Earth elevation", f"{now['earth_alt']:.2f}°")
        c2.metric("Earth above terrain", f"{now['earth_margin']:+.2f}°")
        c3.metric("Earthset in" if now["earth_now"] else "Earthrise in", fmt_hours(now["earth_change_h"]))
        tab_sky, tab_pan, tab_3d = st.tabs(["Sky view", "Panorama", "3D terrain"])
        with tab_sky:
            st.plotly_chart(sky_dome(mask, res["df"], name, use_terrain, now),
                            use_container_width=True, key=f"dome_{k}")
        with tab_pan:
            st.plotly_chart(panorama(mask, res["df"], name, use_terrain,
                                     min(idx, len(res["df"]) - 1)),
                            use_container_width=True, key=f"pano_{k}")
            st.caption("What you would see turning a full circle at the site, north in the middle. "
                       "Press ▶ Play to run the Sun and Earth through the selected period.")
        with tab_3d:
            t3 = site_terrain3d(s)
            if t3 is None:
                st.write("No 3D terrain for this site.")
            else:
                ill = get_illum3d(s["id"]) if s["id"] != lc.CUSTOM_ID else None
                modes = ["Shadows now"]
                if ill is not None:
                    modes += ["Long-term sunlight (NASA)", "Long-term Earth view (NASA)"]
                mode = st.radio("Colour", modes, horizontal=True, key=f"mode3d_{k}")
                if mode == "Shadows now":
                    key3d = f"{s['id']}|{float(s['lat']):.5f}|{float(s['lon']):.5f}"
                    sh = get_shadow(key3d, t3, float(s["lat"]), float(s["lon"]),
                                    round(now["sun_az"], 2), round(now["sun_alt"], 2))
                    st.plotly_chart(terrain_3d(t3, now, name, shadow=sh),
                                    use_container_width=True, key=f"terrain_{k}", theme=None)
                    E, N, lit = sh
                    centre_lit = bool(lit[np.argmin(np.abs(N[:, 0])), np.argmin(np.abs(E[0]))])
                    mask_lit = now["sun_margin"] > 0
                    agree = "agree" if centre_lit == mask_lit else "disagree"
                    st.caption(f"20 × 20 km of LOLA terrain, vertical scale ×{VERT_EXAG:g}. Dark ground is "
                               "in shadow at the chosen time, including shadows cast by ridges up to 100 km "
                               "away. Red dot: landing site. Lines point to the Sun and Earth; dashed means "
                               f"hidden. Shadow check at the site: cast shadows say "
                               f"{'sunlit' if centre_lit else 'shadow'}, horizon mask says "
                               f"{'sunlit' if mask_lit else 'shadow'} ({agree}).")
                else:
                    is_sun = mode.startswith("Long-term sunlight")
                    inferno = [[0, "#16121E"], [0.1, "#1B0C41"], [0.2, "#4A0C6B"], [0.3, "#781C6D"],
                               [0.4, "#A52C60"], [0.5, "#CF4446"], [0.6, "#ED6925"], [0.7, "#FB9B06"],
                               [0.85, "#F7D13D"], [1, "#FCFFA4"]]
                    viridis = [[0, "#0E1A2B"], [0.25, "#1F3F6B"], [0.5, "#2F6FB5"],
                               [0.75, "#7FA8DA"], [1, "#E8F1FB"]]
                    overlay = (ill["sun"] if is_sun else ill["earth"],
                               "Sunlit" if is_sun else "Earth in view",
                               inferno if is_sun else viridis)
                    st.plotly_chart(terrain_3d(t3, now, name, overlay=overlay),
                                    use_container_width=True, key=f"terrain_{k}", theme=None)
                    st.caption("Colour: share of time over 18.6 years that each spot sees "
                               f"{'any part of the Sun' if is_sun else 'any part of Earth'} "
                               "(NASA LOLA average visibility maps, Mazarico et al. 2011). "
                               "Red dot: landing site.")

st.subheader("Artemis III landing windows")
st.caption("Stretches of continuous sunlight long enough for a 6.5-day surface stay. "
           "Landing any time between 'Land from' and 'Land by' keeps the site in sunlight "
           "for the whole stay. 'Period edge' means the stretch continues beyond the selected dates.")
win_cols = st.columns(len(results))
for col, (name, res) in zip(win_cols, results.items()):
    wins = res["m"]["mission_windows"]
    with col:
        st.markdown(f"**{name}**")
        if not wins:
            st.write("No sunlit stretch of 6.5 days or more in this period. "
                     "Try a longer period or another start date.")
            continue
        st.dataframe(pd.DataFrame([{
            "Land from": w["start"].strftime("%Y-%m-%d %H:%M"),
            "Land by": w["land_by"].strftime("%Y-%m-%d %H:%M"),
            "Sunlit for": fmt_hours(w["hours"]) + (" (period edge)" if w["cut_off"] else ""),
            "Earth in view": f"{w['earth_pct']:.0f}%",
            "Longest blackout": fmt_hours(w["blackout_h"]),
        } for w in wins]), hide_index=True, use_container_width=True)

st.subheader("How much does a 100 m landing error matter?")
st.caption("Artemis III aims to land within about 100 m of its target. Each circle is a point "
           "100 m or 200 m from the site centre, coloured by the chosen metric over the selected "
           "period. The dotted ring marks 100 m.")
if not use_terrain:
    st.info("Turn terrain on to see this: on a smooth sphere every nearby point looks the same.")
else:
    metric_options = {"Earth in view": "earth_pct", "Sunlight": "sunlight_pct",
                      "Sun and Earth together": "ops_pct"}
    metric_label = st.radio("Metric", list(metric_options), horizontal=True)
    key = metric_options[metric_label]
    sens_cols = st.columns(len(results))
    for col, (name, res) in zip(sens_cols, results.items()):
        offsets = get_offsets(res["site"]["id"])
        with col:
            st.markdown(f"**{name}**")
            if offsets is None:
                st.write("No offset data for this site.")
                continue
            sens = lc.sensitivity(res["track"], offsets)
            st.plotly_chart(sensitivity_map(sens, key, metric_label), use_container_width=True)
            r = np.hypot(sens["east_m"], sens["north_m"])
            near = sens.loc[r <= 100.5, key]
            st.caption(f"{metric_label} within 100 m: {near.min():.0f}–{near.max():.0f}%. "
                       f"Within 200 m: {sens[key].min():.0f}–{sens[key].max():.0f}%.")

st.subheader("When are the Sun and Earth above the horizon?")
st.caption("Above zero means at least part of the disc clears the local horizon.")
st.plotly_chart(timeline(results[name_a]["df"], results[name_b]["df"], name_a, name_b, when),
                use_container_width=True)

with st.expander("Method, validation and references"):
    st.markdown("""
**Method.** Sun and Earth positions are computed with Skyfield using the JPL DE421 ephemeris
and the MOON_ME_DE421 lunar frame (libration included, no atmospheric refraction).
Each site has a 360° terrain horizon built from LOLA elevation models (80 m/px near field,
240 m/px far field, 150 km range, lunar curvature corrected). A body is visible when any part
of its disc clears that horizon.

**Validation.** Sun and Earth positions were checked against the JPL Horizons API at all six
sites for every day of 2027 (4,392 comparisons); the largest difference is 0.000013°.
Over an 18.6-year period, sunlight fractions at the six sites are within 4 percentage points
of NASA's LOLA average illumination maps.

**Site coordinates.** For each NASA Artemis III candidate region, the point with the highest
long-term average illumination inside the region. Past landings use published landing
coordinates. Chandrayaan-3 lies outside the 80 m terrain model, so its horizon uses 240 m
terrain only and has no 100 m offset analysis.

**Custom coordinates.** Any point can be entered. Its horizon is built the same way on a
down-sampled copy of the LOLA terrain (240 m south of 80°S, 960 m to 60°S); north of 60°S
the Moon is treated as a smooth sphere. Tested on the nine listed sites over 2027, sunlight
from the coarse terrain is within 1 percentage point of the full-resolution result and Earth
visibility within 1.5 points, except on the sharp Malapert ridge (88% vs 100%), where hills
smaller than 240 m decide when Earth is hidden.

**Power.** Panel output = 1361 W/m² × area × efficiency × cos(solar elevation) × the visible
fraction of the solar disc (circular segment above the local horizon). Battery size is the largest
drop in cumulative (output − load) over the period, the standard energy-balance sizing.

**Landing error.** Horizon masks are also computed for 16 points 100 m and 200 m from each site.
Sun and Earth directions shift by less than 0.01° over that distance, so differences come from
terrain alone. The 80 m/px terrain model limits detail at this scale.

**References**
- Rhodes, B. Skyfield (MIT license). https://rhodesmill.org/skyfield/
- Folkner, W. M. et al. (2008). The Planetary and Lunar Ephemeris DE421. JPL IOM 343R-08-003.
- JPL Solar System Dynamics Group. Horizons System. https://ssd.jpl.nasa.gov/horizons/
- Barker, M. K. et al. (2023). A New View of the Lunar South Pole from the Lunar Orbiter Laser Altimeter (LOLA). Planetary Science Journal 4, 183. LOLA south pole DEMs via NASA GSFC PGDA: https://pgda.gsfc.nasa.gov/products/90
- Mazarico, E. et al. (2011). Illumination conditions of the lunar polar regions using LOLA topography. Icarus 211, 1066–1081. Average illumination maps via NASA GSFC PGDA: https://pgda.gsfc.nasa.gov/products/69
- NASA (2022, 2024). Artemis III candidate landing regions.
- Artemis III candidate landing region boundaries (2022), accessed via LROC QuickMap, NASA/GSFC/Arizona State University. https://quickmap.im-ldi.com
- Landing coordinates: IM-2 Athena, NAIF CLPS IM-2 frame kernel (clps_prime1_im2_v01.tf); IM-1 Odysseus, LROC Featured Image 1360; Chandrayaan-3 Vikram, LROC Featured Image 1314 and QuickMap landing-site feature (NASA/GSFC/Arizona State University).
- Robinson, M. S. et al. (2010). Lunar Reconnaissance Orbiter Camera (LROC) Instrument Overview. Space Science Reviews 150, 81–124.
""")