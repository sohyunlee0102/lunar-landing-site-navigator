# Validation

All numbers below come from runs of this project's code. Sunlight and Earth visibility use the
"any part of the disc above the horizon" rule unless stated.

## 1. Sun and Earth positions vs JPL Horizons

Skyfield (DE421) against the JPL Horizons API (DE441), airless apparent azimuth and elevation,
every day of 2027 at 00:00 UTC. 6 sites × Sun and Earth × 366 days = 4,392 comparisons.
Script: `scripts/validate_horizons.py`.

| Site | Body | Max elevation difference | Max azimuth difference |
|---|---|---|---|
| Haworth | Sun / Earth | 0.000013° / 0.000012° | 0.000008° / 0.000010° |
| Malapert Massif | Sun / Earth | 0.000013° / 0.000011° | 0.000009° / 0.000010° |
| Mons Mouton | Sun / Earth | 0.000013° / 0.000011° | 0.000009° / 0.000010° |
| Nobile Rim 1 | Sun / Earth | 0.000013° / 0.000011° | 0.000009° / 0.000010° |
| Nobile Rim 2 | Sun / Earth | 0.000013° / 0.000011° | 0.000009° / 0.000010° |
| de Gerlache Rim 2 | Sun / Earth | 0.000013° / 0.000012° | 0.000008° / 0.000010° |

The small, uniform offset reflects the different ephemeris versions.

## 2. Terrain-aware visibility vs NASA LOLA average maps

18.6 years at 6-hour steps, observer at ground level, compared with NASA GSFC average
visibility maps (Mazarico et al. 2011).

| Point | Sunlight (ours / NASA) | Earth in view (ours / NASA) |
|---|---|---|
| Brightest pixel of NASA map (−89.47°, −137.44°) | 87.8% / 88.4% | – |
| (−89.0°, 0.0°) | 15.0% / 14.5% | 45.6% / 45.4% |
| (−88.0°, 0.0°), crater floor | 0.0% / 0.0% | 25.9% / 26.1% |
| Haworth | 67.8% / 68.6% | 60.0% / 59.4% |
| Malapert Massif | 81.7% / 84.5% | 79.3% / 71.0% |
| Mons Mouton | 53.2% / 53.8% | 100.0% / 100.0% |
| Nobile Rim 1 | 81.9% / 85.8% | 58.6% / 60.2% |
| Nobile Rim 2 | 53.8% / 53.9% | 77.9% / 71.8% |
| de Gerlache Rim 2 | 73.9% / 74.3% | 61.7% / 61.8% |

Sunlight agrees within 4 points. Our values sit slightly low because site coordinates were chosen
as the brightest pixel of NASA's map, which biases NASA's value upward.

**Earth visibility at Malapert and Nobile Rim 2 (+6 to +8 points).** Extending the horizon search
from 150 km to 300 km and 500 km changed nothing (Malapert 79.3%, Nobile Rim 2 77.9%, Haworth
60.0% at all three). NASA's own map varies sharply around these points: within 600 m Earth
visibility ranges 24–100% at Malapert and 38–80% at Nobile Rim 2, against 40–60% at Haworth.
Both sites sit on ridge edges where a single pixel changes the answer.

## 3. Real missions

| Mission | Check | Result |
|---|---|---|
| IM-1 Odysseus | Terrain height at landing site | 2,592 m (ours) vs 2,579 m (LROC) |
| Chandrayaan-3 | Local sunset after 23 Aug 2023 landing | About 4 Sep 2023, 07:00 UTC; ISRO put the rover to sleep on 2 Sep and the lander on 4 Sep |
| Apollo 11 | Sun and Earth elevation at landing | 20:00 UTC: Sun 10.55°, Earth 59.23°; Apollo Lunar Surface Journal at 20:17:39 UTC: Sun 10.65°, Earth 59.4°. The Sun rises about 0.5° per hour. |

## 4. Coarse terrain used for custom coordinates

Each listed site run through the coarse terrain shipped with the app and the full-resolution
masks, 2027, 2-hour steps.

| Site | Coarse resolution | Mean horizon difference | Sunlight (full / coarse) | Earth (full / coarse) |
|---|---|---|---|---|
| Haworth | 240 m | 0.06° | 69.6 / 69.1% | 59.0 / 58.8% |
| Malapert Massif | 240 m | 0.65° | 85.8 / 86.1% | 88.2 / 100.0% |
| Mons Mouton | 240 m | 0.06° | 52.3 / 52.4% | 100.0 / 100.0% |
| Nobile Rim 1 | 240 m | 0.91° | 89.7 / 90.5% | 58.7 / 60.2% |
| Nobile Rim 2 | 240 m | 0.01° | 53.5 / 53.4% | 81.7 / 81.4% |
| de Gerlache Rim 2 | 240 m | 0.27° | 75.9 / 75.9% | 57.9 / 57.9% |
| IM-2 Athena | 240 m | 0.03° | 45.5 / 45.6% | 92.8 / 92.9% |
| IM-1 Odysseus | 240 m | 0.25° | 38.7 / 39.2% | 100.0 / 100.0% |
| Chandrayaan-3 | 960 m | 0.13° | 47.0 / 47.5% | 100.0 / 100.0% |

The app's position-sensitivity warning (results at points 250 m away, over a year) flags
Malapert (sunlight 53–86%, Earth 61–100%) and passes Haworth (60–69%, 56–60%).

## 5. Internal consistency

- **3D cast shadows vs horizon mask.** Computed independently (ray marching on the terrain grid
  vs the 360° horizon). At Haworth, 6 Jan 2027 22:00 UTC both say sunlit; 7 Jan 09:00 UTC both say shadow.
- **Battery model.** A synthetic 30-hour darkness with a 150 W load gives 4.5 kWh exactly.
  At Malapert in January 2027 the battery (4.7 kWh) matches the longest stretch below load (32 h × 150 W).

## 6. Differences between NASA maps

NASA's 60 m (85°S) and 120 m (75°S) average illumination maps disagree on narrow ridges:
at our site coordinates, Malapert 63% vs 84%, Nobile Rim 1 66% vs 85%, Haworth 56% vs 69%,
de Gerlache Rim 2 65% vs 74%. Our own calculation agrees with the 120 m map, which was also used
to choose site coordinates, so the app uses the 120 m map throughout.