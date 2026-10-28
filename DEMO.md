# Demo outline (maximum 10 minutes)

## Customer overview (up to 5 minutes)

1. Explain the planning problem and scope: Elexon GB wind, historical January decisions, no demand or purchase calculation.
2. Open Decision view. Select a date and cutoff, identify the next civil delivery day, follow the hourly MW curve, and open the publication-time table. Explain that the default cutoff and civil-day horizon are assumptions.
3. Open Accuracy view. Explain that actuals are subsequently observed. Show matched coverage, MAE, RMSE and signed bias; positive bias means overforecast. Change the date range to a single day to compare forecast and actual and inspect the table.
4. Explain practical limitations: the error history is context, not a confidence interval or an order recommendation.

## Technical overview (up to 5 minutes)

1. Show React/Vite calling the same-origin FastAPI endpoint and the Docker/Heroku packaging.
2. Trace the manifest/checksum validation and immutable WINDFOR/FUELHH rows; explain no request-time source fetch.
3. Show per-target latest publication at or before cutoff, missing values, and the mean of both half-hour actuals. Explain retrospective revisions and signed error.
4. Run the reference and unit tests and show a changed cutoff produces recalculated results. Explain coverage and input bounds.
5. Show startup/deployment instructions, verification status and limits. Show the actual deployed URL only after it exists and has been checked.
