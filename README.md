# Fare watch

Checks one route on Google Flights once a day through SerpApi, records every
reading in `fares.csv`, and emails you only when the fare crosses a threshold
you set.

Currently configured for **EWR–BOM, Dec 12–22 2026, business, nonstop only**,
with a $4,000 buy target and a $6,000 walk-away ceiling.

## Layout

```
your-repo/
├── check_fares.py
├── fares.csv                    created on the first run
└── .github/
    └── workflows/
        └── fare-watch.yml
```

## Setup

**1. Create the repo.** Public repos get unlimited Actions minutes; private
repos draw on the 2,000 free minutes a month, and this job uses roughly 20
seconds a run, so either is fine. Nothing secret is stored in the files.

**2. Get a SerpApi key.** Sign up, copy the key from the dashboard. The free
plan covers 250 searches a month; this job uses one a day.

**3. Create a Gmail app password.** Turn on 2-step verification on the Google
account, then go to Google Account → Security → App passwords and generate one
for "Mail". Your normal Gmail password will not work for SMTP.

**4. Add four repository secrets** under Settings → Secrets and variables →
Actions:

| Secret | Value |
|---|---|
| `SERPAPI_KEY` | Your SerpApi key |
| `SMTP_USER` | your.address@gmail.com |
| `SMTP_PASSWORD` | The 16-character app password, no spaces |
| `EMAIL_TO` | Where alerts should go |

For a non-Gmail provider, also set `SMTP_HOST` and `SMTP_PORT` in the workflow's
`env:` block. The script defaults to Gmail on port 465.

**5. Run it once by hand.** Actions tab → Fare watch → Run workflow. Check the
log: it prints the fare it found whether or not it sends an email. If email
isn't configured yet, it prints the alert to the log instead of failing.

## Changing the trip

Route, dates, cabin, and the nonstop filter are in the `TRIP` dict at the top of
`check_fares.py`. Thresholds are in the workflow's `env:` block, so you can
adjust your buy target without touching the script.

`travel_class`: 1 economy, 2 premium economy, 3 business, 4 first.
`stops`: 1 for nonstop only; remove the line to allow connections.

## When it emails you

Daily mail about an unchanged fare teaches you to ignore the alerts, so it only
writes when one of three things is true:

- the fare is at or below your buy target
- it's a new low since tracking began
- it dropped $250 or more since the previous check

Failures also email you, so silence means the job is running and nothing
happened — not that it quietly broke.

## Things that will bite you

**Scheduled workflows get disabled after 60 days of repository inactivity.** The
daily commit of `fares.csv` counts as activity, so this stays alive on its own,
but if you fork it and strip the commit step, set a calendar reminder.

**GitHub's cron is best-effort.** Jobs on the free tier often start 5–30 minutes
late, sometimes more during busy periods. Fine for fare tracking, useless for
anything that needs to fire at a precise moment.

**It only sees published fares.** Consolidator business class pricing and all
award inventory are invisible to Google Flights, so a quiet tracker doesn't mean
there's nothing good out there.

**The free tier is 250 searches a month.** If you add routes or date pairs,
each one is its own daily call. Four variations is 120 a month; eight will
run you out.
