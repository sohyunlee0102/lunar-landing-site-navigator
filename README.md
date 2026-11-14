# Lunar Landing Site Navigator

**Live app:** https://lunar-landing-navigator.streamlit.app/
*(If the app has gone to sleep, press "Yes, get this app back up" and allow about a minute.)*

A tool for mission planners, educators and the public to compare lunar south pole landing sites and dates quickly. It shows where the Sun and Earth sit relative to the real local horizon, how long each stays up, and what that means for solar power, batteries and direct-to-Earth communication. NASA's Artemis III candidate regions serve as a reference set of real south pole sites; any mission can set its own surface stay or enter its own coordinates.

Built for the 2026 NASA Space Apps Challenge, *Lunar Landing Site Navigator*.

## What it does

- **Landing calendar.** For every day of a year, which candidate site gives continuous sunlight for your mission's surface stay (default 6.5 days, the Artemis III plan), and how much of that stay Earth is in view.
- **Side-by-side comparison** of any two sites: sunlight, solar elevation, Earth visibility, longest darkness and communication blackout, landing windows.
- **A chosen moment.** Drag through time to see solar and Earth elevation, how far each clears the terrain, and how long until sunset or Earthset.
- **Sky view, horizon panorama (with ▶ animation) and 3D terrain** with cast shadows, plus NASA's 18.6-year sunlight and Earth-visibility maps draped over the terrain.
- **Power and battery.** Output of a vertical Sun-tracking panel and the battery a constant load needs, sized by energy balance.
- **How much does 100 m matter?** Results at 16 points 100 m and 200 m around each site, matching Artemis III's landing accuracy.
- **Sites:** six Artemis III candidate regions, past landings (IM-1, IM-2, Chandrayaan-3, Apollo 11), or any custom coordinates.
- **Terrain on/off** to show what a smooth-sphere calculation gets wrong.

## What we found

- **No single site works year-round.** For the 6.5-day Artemis III stay in 2027, each candidate region works on 124–278 days. Together they leave only 19 days with no option, which is why NASA keeps several regions.
- **100 m decides Earth contact on ridges.** At Malapert Massif, landing 100 m north keeps Earth in view all the time; 100 m south cuts that roughly in half. NASA's own visibility map shows the same pattern.
- **Terrain cuts both ways.** A crater floor at 88°S that looks 29% operable on a smooth sphere is never sunlit. High ridges see below the flat horizon and gain Sun and Earth time.
- **Grazing sunlight is not power.** A few hours of Sun peeking through a notch can split a 3-day darkness in two on paper, but barely recharges a battery. Sizing by energy balance catches this.

## Method

- **Sun and Earth positions:** Skyfield with the JPL DE421 ephemeris and the MOON_ME_DE421 lunar frame. Libration is included; there is no atmospheric refraction on the Moon.
- **Horizon:** for each site, the highest terrain angle in each of 360 directions out to 150 km, from LOLA elevation models (80 m near field, 240 m far field), corrected for lunar curvature.
- **Visibility:** a body counts as visible when any part of its disc clears the horizon, the same rule as NASA's LOLA illumination maps.
- **Site coordinates:** within each Artemis III candidate region, the point with the highest long-term average sunlight. Past landings use published coordinates.
- **Power:** 1361 W/m² × area × efficiency × cos(solar elevation) × the visible fraction of the solar disc.
- **Custom coordinates:** the same horizon method on a down-sampled terrain model shipped with the app (240 m south of 80°S, 960 m to 60°S, smooth sphere further north).

Positions are computed locally rather than queried from JPL Horizons so the app responds in seconds and does not depend on an external service. They were checked against Horizons (below).

## Validation

Full results: [docs/validation.md](docs/validation.md)

| Check | Result |
|---|---|
| Sun and Earth positions vs JPL Horizons API, 6 sites, every day of 2027 (4,392 comparisons) | Largest difference 0.000013° |
| 18.6-year sunlight vs NASA LOLA average illumination maps, 6 sites | Within 4 percentage points |
| Terrain height at IM-1 landing site vs LROC | 2,592 m vs 2,579 m |
| Chandrayaan-3: local sunset ≈ 4 Sep 2023 | ISRO put the rover and lander to sleep on 2 and 4 Sep 2023 |
| Apollo 11 at landing (20 Jul 1969): Sun 10.55°, Earth 59.2° | Apollo Lunar Surface Journal: 10.65°, 59.4° (17 min later) |
| 3D cast shadows vs horizon mask at the landing site | Agree on whether the site is lit |

Reproduce the Horizons check with `python scripts/validate_horizons.py`.

## Limitations

- Terrain detail below 80 m is not modelled, so the 100 m analysis is approximate on sharp ridges.
- Custom coordinates use coarser terrain. On the sharp Malapert ridge this gives 100% Earth visibility against 88% at full resolution; the app warns when results vary strongly within 250 m.
- NASA's 60 m and 120 m average illumination maps differ by up to 20 percentage points on narrow ridges. Site selection and 3D colouring use the 120 m map consistently.
- 3D shadows are computed on a 200 m grid and do not model the solar disc's partial occlusion.
- The power model assumes an ideal Sun-tracking vertical panel and a constant load.

## Run locally

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Repository layout

```
app.py                Streamlit interface
lunar_core.py         Ephemeris, visibility, metrics, power, coarse terrain, shadows
assets/               Precomputed horizon masks, 3D terrain, NASA map samples, ephemeris files
scripts/              Validation scripts
docs/validation.md    Validation results
```

The precomputed assets were generated offline from the LOLA DEMs listed below.

## Data and references

- Rhodes, B. Skyfield. https://rhodesmill.org/skyfield/
- Folkner, W. M. et al. (2008). The Planetary and Lunar Ephemeris DE421. JPL IOM 343R-08-003.
- JPL Solar System Dynamics Group. Horizons System. https://ssd.jpl.nasa.gov/horizons/
- Barker, M. K. et al. (2023). A New View of the Lunar South Pole from the Lunar Orbiter Laser Altimeter (LOLA). *Planetary Science Journal* 4, 183. DEMs: https://pgda.gsfc.nasa.gov/products/90
- Mazarico, E. et al. (2011). Illumination conditions of the lunar polar regions using LOLA topography. *Icarus* 211, 1066–1081. Maps: https://pgda.gsfc.nasa.gov/products/69
- NASA (2022, 2024). Artemis III candidate landing regions. Region boundaries accessed via LROC QuickMap, NASA/GSFC/Arizona State University. https://quickmap.im-ldi.com
- Robinson, M. S. et al. (2010). Lunar Reconnaissance Orbiter Camera (LROC) Instrument Overview. *Space Science Reviews* 150, 81–124.
- Landing coordinates: IM-2 (NAIF CLPS frame kernel), IM-1 and Chandrayaan-3 (LROC), Apollo 11 (NSSDCA, Wagner et al. 2017).
- Apollo 11 Sun and Earth positions at landing: Apollo Lunar Surface Journal, NASA.

## Third-party software and data licenses

| Component | Use | License |
|---|---|---|
| Streamlit | Web app framework | Apache 2.0 |
| Plotly | Charts and 3D views | MIT |
| Skyfield | Sun and Earth positions | MIT |
| NumPy | Numerical computing | BSD 3-Clause |
| pandas | Data handling | BSD 3-Clause |
| rasterio, pyproj, SciPy | Offline preprocessing of terrain data (not used by the app) | BSD 3-Clause, MIT, BSD 3-Clause |
| JPL DE421 ephemeris and lunar frame kernels | Planetary positions | NASA/JPL data, publicly available |
| LOLA DEMs and average illumination maps (NASA GSFC PGDA) | Terrain and validation | NASA data, publicly available |
| Artemis III candidate region boundaries via LROC QuickMap | Site selection | NASA/GSFC/Arizona State University; used with credit under LROC's terms for non-commercial use |

## License

MIT. See [LICENSE](LICENSE).