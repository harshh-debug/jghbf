# Data and analysis methodology

## Evidence hierarchy

1. The user's original assignment defines the scope.
2. `evidence/elexon-openapi-subset.json` captures the official schemas and parameter descriptions for the two required endpoints.
3. `data/raw` plus `data/manifest.json` record the actual responses used here.
4. Design assumptions below fill gaps in the brief; they are not claims about a particular exchange's rules.

## Verified endpoint behavior

Base URL: `https://data.elexon.co.uk/bmrs/api/v1`.

| Endpoint | Verified request parameters used | Important semantics |
| --- | --- | --- |
| `/datasets/WINDFOR/stream` | `publishDateTimeFrom`, `publishDateTimeTo` | Filters publication time, not target/delivery time; without filters retrieves the latest publication |
| `/datasets/FUELHH/stream` | `settlementDateFrom`, `settlementDateTo`, `fuelType=WIND` | Settlement date format is `yyyy-MM-dd`; settlement-date and publication-date filters must not be mixed |

Both stream responses are top-level arrays, not `{"data": [...]}`. Inspect the supplied JSON. Do not copy wrappers from the nonstream endpoint examples. Actuals also have `publishTime`, `settlementDate` and `settlementPeriod`; retain them when useful, but use timezone-aware target timestamps for alignment.

FUELHH describes its values as mean MW over each half-hour. The forecast schema's `generation` is numeric and nullable. The Elexon wind page describes hourly forecasts and MW values. Real downloaded forecasts occur on the hour; actuals occur on the hour and half-hour. Do not infer forecast cadence from the actuals cadence mentioned in the brief.

The brief calls the client a UK utility, while these sources describe Great Britain generation and wind visible to the system operator with operational metering. Keep labels tied to the selected Elexon series. Do not claim the series covers every UK wind turbine, all embedded renewables, or Northern Ireland.

## Scope and timezone

Use `Europe/London` for user-facing decision dates and cutoff times. Parse Elexon ISO `Z` timestamps as UTC. January and February 1, 2026 have no UK DST transition, so the default 31 delivery days each contain 24 hours. Do not extend the reference's hardcoded 24-hour day loop to other seasons without changing it.

For decision date D in January 1–31, let the target day be the civil date D+1, `[00:00, 24:00)` in London. This yields January 2 through February 1, or 744 hourly targets. December 30–31 publication buffers allow the first decision to choose older eligible revisions if necessary. January 1 actuals are a source-data buffer, excluded from the default analysis.

This is a pilot convention, not an implemented exchange calendar. The client does not name an exchange/product. The Nord Pool GB regulations effective January 1, 2026 describe a calculation day starting at 23:00 UK time; therefore a civil-midnight day must not be described as the N2EX delivery calendar. Supporting venue-specific calendars would require confirmed client requirements and is outside this pilot.

## Decision cutoff

Default: 09:00 Europe/London. This is a labeled illustrative operating cutoff, not a claimed universal auction gate. The Nord Pool support page lists N2EX gate closure as 09:50 GMT, so 10:00 is unsuitable as a generic preauction default. Keep a configurable `HH:MM` cutoff for the historical analysis; custom values need not represent executable trading schedules.

Treat `publishTime` as the availability proxy because it is the timestamp provided by the assignment. The data does not include receipt delays. Do not claim nanosecond-precise as-traded reconstruction.

## Forecast-vintage selection

For target hour h and decision cutoff c:

1. Find all WINDFOR rows with `startTime == h`.
2. Keep only rows with `publishTime <= c`.
3. Select the row with the maximum eligible publication timestamp.
4. If none exists, forecast is null and coverage is missing.
5. If the latest eligible row has null generation, retain the missing value; do not silently roll back to an older nonnull revision.

Select per target; a publication can lack some targets. Show publication timestamps per point and a range if the selected points come from multiple publications. Do not fetch `latest`, sort solely by target, or take the newest revision regardless of cutoff. Retain each target's chosen publication so the result is auditable.

Cutoff equality is eligible. Source rows are unordered; do not rely on API response order.

## Alignment convention

Use one hourly point per delivery hour. Define observed hourly power as:

`actual_hourly_mean_mw[h] = (actual_mw[h] + actual_mw[h + 30 minutes]) / 2`

Compare that value with `forecast_mw[h]`. Require both actual half-hours to be present and nonnull. Use the latest downloaded actual revision for each half-hour as retrospective truth. Actual publication after decision time is expected: actuals are scored later, not used to build the forecast.

The hourly cadence and actual half-hour averaging are verified; interpreting each forecast-at-h as the following hour's representative power is an explicit pilot comparison convention. The saved forecast schema does not explicitly establish whether its value is an hour-average versus point prediction. State this limitation, and do not label this convention a confirmed Elexon settlement rule. Do not silently interpolate forecasts, shift timestamps, double the sample size, or claim both derived half-hours are independent forecasts.

If clearer source documentation establishes a different interval convention, document and consistently change it, regenerate reference outputs, and adjust the meaningful tests. Do not change it solely to produce a better-looking score.

## Metrics

For each matched hour i, `e_i = forecast_i - actual_i`, measured in MW.

| Metric | Definition | Interpretation |
| --- | --- | --- |
| MAE | `sum(abs(e_i)) / n` | Typical absolute forecast error; lower is better |
| RMSE | `sqrt(sum(e_i ** 2) / n)` | Emphasizes larger misses; lower is better |
| Signed bias | `sum(e_i) / n` | Positive means wind overforecast; negative means wind underforecast |
| Coverage | `matched_hour_count / expected_hour_count` | Explains the denominator and missing observations |

Compute pooled range metrics over matched hourly errors, rather than averaging daily RMSE values. Daily breakdowns use each day's matched points. All metrics must update when the date range or cutoff changes. Empty comparisons return null metrics and `matched_hours=0`, never zero-error success or JSON NaN.

Avoid MAPE: zero or near-zero wind makes percentages unstable. Avoid an unspecified "accuracy percentage". MAE is not a confidence interval. Do not create shaded probabilistic bands from `forecast ± MAE`.

A positive wind error means the planner expected more wind than materialized, which can create an additional supply requirement relative to plan. A negative error means more wind materialized than expected. These are qualitative implications, not proof of monetary loss or a customer-specific order volume.

Power is MW. Energy over a half-hour is `MW * 0.5 hours`; over an hour it is `MW * 1 hour`. Do not sum MW and label it energy. Energy totals are optional and not needed for the minimal product.

## Retrospective and decision-time information

The Decision view shows only the selected forecast by default. If retrospective actuals are overlaid, visibly label them as subsequently observed. Whole-January accuracy is retrospective evaluation; it was not known on the first day of January.

Do not present whole-month MAE/bias as a risk estimate available at every January decision. This pilot does not need a live rolling error model. If an optional past-only summary is added, actual publication timestamps must also be before the selected cutoff, and the available history/limited sample must be shown. Prefer omitting that feature within the time budget.

## Data quality policy

- Preserve raw bytes and exact request URLs with checksums.
- Deduplicate identical rows across acquisition windows. A conflicting value for the same dataset/target/publication is a data-integrity error, not an arbitrary `drop_duplicates` choice.
- Keep distinct revisions for the same target. Latest eligible forecast and latest downloaded actual use different selection rules.
- Nulls are missing. Zero is a valid measured value. Negative/suspicious values should be flagged and investigated, not silently clamped.
- Validate types and finite numbers. Unexpected schemas fail visibly.
- Filter to the intended target horizon locally; publication filters alone return targets outside the analysis window.
- Do not assume upstream date bounds are half-open. Exact requests and observed response ranges are in the manifest/report.
- No runtime source fallback, random numbers, or simulated dataset on API failure.

## Baseline for the included bytes

With 09:00 cutoff and the above convention: 744/744 matched hours; MAE 2038.9126344086021 MW; RMSE 2504.758652899355 MW; signed bias +1747.8870967741937 MW. Exact machine values and daily results are in `data/derived/quality-report.json`. Keep full precision internally; display sensible rounding, such as whole MW.

The snapshot has 19,272 unique forecast rows across 264 publication timestamps, each with 73 target rows, and 1,536 unique wind actuals. There are no generation nulls or exact duplicate rows in this snapshot. These observations do not justify deleting missing-data handling.

Observed January publication clock times include an irregular `12:25` timestamp. The explanatory wind webpage gives a different nominal schedule. Filter actual timestamps; never manufacture publication times or assume a fixed daily schedule.
