# Theme Strength Board

Every weekday at about 10:05 AM ET, GitHub Actions scores 24 market themes against SPY,
publishes the dashboard to GitHub Pages, and sends a phone alert through ntfy.

- `themes.json` – themes, their ETF (optional) and leader stocks. Edit to add or change themes.
- `sector_strength.py` – scoring. Thresholds are at the top (`BUY_RS`, `LEAD_RS`, `WEAK_RS`).
- `dashboard_template.html` – the page design; the script fills in the data.
- `history.json` – one row of RS per session; drives the "Day" counter. Committed by the workflow.
- `.github/workflows/theme-strength.yml` – the schedule.

Data: TradingView screener (free, ~15 minutes delayed). A screen for ideas, not trading advice.

## Manual run
GitHub → Actions → "Morning theme strength" → Run workflow.

## Phone alert
Install the ntfy app, subscribe to the topic stored in the repository secret `NTFY_TOPIC`.
