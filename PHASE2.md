# Superseded sending instructions

Direct sending is now disabled. Use [REVIEW_WORKFLOW.md](REVIEW_WORKFLOW.md).
The rules below remain reference; historical sending commands no longer publish.

# Phase 2: rule-based recommendations

`phase2.py` is an opt-in addition to the inspected repository. It reuses
`main4_pkge_indi.py`'s `fetch_full_forecast` and installed curl_cffi transport,
including retries/fallbacks. No existing forecast script or schedule was changed.
There are multiple existing scheduled workflows; several send twice. Review these
before scheduling Phase 2 to avoid duplicate reports.

## Run

Install the existing `requirements.txt`, then:

```sh
python -m unittest discover -s tests -v
python phase2.py                  # tomorrow, preview only
python phase2.py --date 2026-10-30 # explicit Bali date, within fetched 3 days
python phase2.py --send           # explicitly post preview-equivalent report
python phase2.py --fixture normalized.json --date 2026-10-30
```

The fixture is a normalized `fetch_full_forecast` response, not raw Surfline JSON.
Fixture posting and direct posting are disabled. Delivery uses the review workflow
and existing Telegram secrets. Deterministic reports are split between complete
sections when necessary; all parts need one fresh approval before publication.

## Rules and assumptions

These are recommendations for Old Man's / Batu Bolong, not validated safety
thresholds for all Bali breaks. Advanced beginners are included in beginner.
All daylight intervals are evaluated for three tiers; the simple report groups
matching time windows under 🟢 BEGINNER, 🟡 INTERMEDIATE and 🔵 ADVANCED, followed
by ⚠️ CAUTIONS only when relevant. Surfers of higher skill may still choose smaller waves with a
longboard/foamie. The header is `Forecast date: 30 October 2026`, a blank line,
then `📍OLD MAN'S / BATU BOLONG` (with the actual target date and spot).
Good windows show only the times for every skill level, including advanced.
Short comments appear only for necessary restrictions (inside break only, coach
recommended, strong wind or another conditional limitation). Heights and long
reason lists are not displayed beside otherwise good windows. Adjacent windows
merge when their usable advice matches, even if underlying wave heights change;
no height is averaged or invented. Disjoint matching windows use `and`; missing-data
and flat, not-recommended periods remain explicit. Analysis uses only complete
daylight hours: round sunrise up and sunset down. For example, 05:48–18:12 becomes
06:00–18:00. Exact-hour endpoints stay unchanged, and no complete hour means the
report is withheld. Raw hourly measurements stay
in the saved forecast rather than an hourly table in the message.
The WITA label, source
line and generic safety-guarantee disclaimer have been removed at the user's
request. Times still use Bali time, and the interval-specific skill/coach cautions
remain. Revisions of saved drafts use the same display format and need fresh review.

* Breaking heights use **maximum forecast breaking surf**, not swell height.
  Beginner ceiling is 2 ft inclusive; intermediate ceiling 4 ft inclusive;
  above 4 ft outside surf is advanced. Heights/ranges still determine restrictions
  internally; they are not routine commentary in the displayed report.
* Beginner advice always starts inside/whitewater. Above 2 ft, 600 kJ or 12 s,
  retain the user's inside exception with coach assessment and a reminder that
  actual inside waves must be at most 2 ft. This does not assert inside waves
  are smaller than the forecast or that entry is safe.
* Intermediate energy above 1,000 kJ, breaking surf above 4 ft, or period above
  14 s restricts advice to inside only, with actual inside waves at most 4 ft.
  The period ceilings are conservative assumptions from the user's table.
* Below 100 kJ: nearly flat, not recommended; beginners may still try inside.
  100–199 kJ: weak/small, longboard or 8 ft+ foamie preferred. Beginner reference
  ranges are 200–400 kJ/7–11 s and upper beginner 400–600 kJ/8–12 s.
  Intermediate preferred range is 600–1,000 kJ/10–14 s, mid tide.
  These preferred bands are quality guidance, not lower limits that prohibit surf.
* Energy uses `energy.nearshore`, provisionally interpreted as kJ to match the
  user's thresholds. Upstream exposes this field without a unit guarantee.
  Confirm against Surfline's displayed kJ before relying on live classifications.
  Offshore energy, swell power and height-derived estimates are not substituted.
* Period uses the longest valid supplied swell-partition period, conservatively
  including secondary swells. This can overstate risk from a tiny long-period
  partition. It is not an energy-weighted dominant period.
* Tide is interpolated between samples no more than two hours apart, with no
  extrapolation. Heights are converted from feet to metres. Mid is
  `(daily minimum + daily maximum) / 2`, including available extrema. Low is
  below 33% of that daily range, mid 33–67%, high above 67%. This daily-range
  definition is an assumption; it is not a fixed 1.2 m threshold or half the
  time between high and low. Rising/falling comes from the bracketing samples.
  Beginner prefers mid/high; low adds coach caution. Intermediate/advanced
  prefer mid. Tide does not certify reef clearance; incomplete daily data may
  distort the calculated range.
* Wind converts knots to km/h with factor 1.852. **Above** 20 km/h remains
  conditional for anyone comfortable, with coach recommended for beginners.
  Strong wind appears as a conditional reason; no offshore/onshore claim is made without
  a calibrated break orientation. No wind-only blanket ban.
* Surfline rating is used as quality context. POOR, VERY_POOR, POOR_TO_FAIR
  downgrade otherwise suitable advice to conditional; a good rating never
  overrides skill, height, energy, tide or wind cautions. No invented numeric
  ranking or best-hour claim. Low quality appears as a short conditional reason.
* Use Surfline sunrise–sunset, rounded inward to whole hours, not a hardcoded
  schedule. Each timestamped forecast row represents its following hour. Skip
  partial sunrise/sunset hours and all nighttime rows for recommendation analysis.
  Missing hours remain visible as unavailable. Missing sunlight or an empty rounded
  window withholds the report. Bali timezone is Asia/Makassar.
* Show high-energy, wind, flat-surf, inside-limit or weak-surf cautions only when
  triggered by the analyzed daylight rows. Nighttime conditions cannot create a
  caution. Omit the entire cautions section when none applies.
* Missing/negative/nonfinite core inputs are unknown, not zero or safe.
  Tide heights may be negative. A zero tidal range is unknown. Missing rating,
  wind, energy, period, breaking heights or tide prevents a positive recommendation.
  Unknown feed data cannot be rescued with fabricated inside heights.

## Verification

Unit tests cover height/energy/wind boundaries, small powerful beginner surf,
inside exceptions, flat surf, long periods, low tide, rating precedence, invalid
inputs, tide interpolation and gaps, sunrise/sunset coverage, missing intervals,
message splitting, grouped windows without hidden gaps, minimal commentary, flat and
unknown periods, inward daylight rounding, nighttime exclusion, Telegram bold-entity
offsets and offline CLI behavior. Tests are deterministic and never
send to Telegram. Existing root `test_*.py` files are live endpoint probes;
use discovery under `tests/` to avoid invoking those probes.

Live endpoint availability, Surfline energy units, and real Telegram delivery
are separate operational checks; passing tests does not establish those facts.
