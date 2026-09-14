# Recording what the collar saw

**Turn this on.** Every day it stays off is a day of Kona's hour-by-hour
history that cannot be recovered afterwards, by us or by anyone.

```
KONA_DB_PATH=kona.db
```

in `.env`, then restart `kona serve`. That is the whole setup.

---

## Why it matters more than it sounds like it does

Fi's API answers questions about *now*. Ask it for today by the hour and it
answers; ask it for yesterday by the hour and there is no argument to pass —
`pet_hourly()` takes no cursor. At midnight her time, the detail of the day
that just happened stops existing anywhere we can reach. Daily rest totals last
about a fortnight in `restSummaryFeed` and then go the same way.

Until now this app has been a window onto a view that keeps closing. Everything
it has ever shown you was fetched seconds earlier and kept only in memory, and
restarting the server threw it away.

There is a second reason, and it is the one Chris actually asked for. The stated
plan is to stop relying on Fi hardware — an open-source collar, or one built
here. **You cannot judge a replacement against a baseline you did not keep.**
"Is this new collar's step count believable?" is answerable with a year of
recorded Fi readings next to it and unanswerable without.

## What gets written

Everything a refresh saw, in eight tables shaped around a dog's day rather than
around Fi's API:

| Table | One row per | Why it is there |
|---|---|---|
| `hour` | hour of her local day | **The perishable one.** Steps, sleep, naps |
| `day` | calendar day | Totals, the step goal, whether the day was complete |
| `walk` | walk or car ride | Fi's own id, so a walk seen ten times is one row |
| `walk_point` | point of a route | The path, in order |
| `position` | GPS fix | The live trail, keyed on the collar's timestamp |
| `device_state` | collar reading | Battery, signal, mode — for judging other hardware |
| `overnight` | night | Sleep as an interval, not just a total |
| `overnight_interruption` | waking | When she got up |

Every row carries a `source` column, `"fi"` today. That column is the whole
point of the exercise: the day a second collar arrives, "steps" has to be able
to say whose.

`NULL` means *we were not told*. It never means zero. A dog who did not move and
an hour nobody asked about are different facts, and a chart that confuses them
draws a lie.

## What it costs

About **15–20 MB a year**, measured rather than guessed: a full day of fixtures
writes 24 hourly rows, one daily row, a handful of walks with their routes, and
the collar readings and GPS fixes that arrive between them — call it 500 rows a
day, near enough 180,000 a year, at roughly 80 bytes each.

For scale, that is a third of one photograph from the camera tab.

## What it will not do

**It cannot break the app.** `Recorder.record()` catches everything including
its own bugs, and `FiService` catches anything it might still throw, because
every call site is inside a page load. A database that will not open costs one
warning line and recording stays off until the next restart; the Activity tab
carries on exactly as before. This is tested, not asserted.

**It never overwrites something known with nothing.** Fi answers partially all
the time — steps arrive, sleep does not — and the same hour is written over and
over as the day fills in. Every update is `COALESCE(new, old)` in SQL, so a
later, poorer reading cannot erase an earlier, richer one. Without that rule the
store would quietly converge on whatever the last refresh of the day happened
to know.

**Nothing reads from it yet.** Deliberately. The first job is to stop losing
data, and a store with no readers cannot break a page.

## The file is private, and the repository is not

`*.db` is gitignored. Do not commit it and do not paste it anywhere: a year of
a dog's GPS history is a year of her owners' movements, and this repository is
public.

Back it up like a document, not like code — it is the one thing here that
cannot be rebuilt from the source.

## Looking at it

Anything that opens SQLite. It is written in WAL mode, so reading it while
`kona serve` is running is safe and will not block a refresh.

```sql
-- Her last week, hour by hour
SELECT day, hour, steps, sleep_s FROM hour ORDER BY day DESC, hour LIMIT 168;

-- Every walk, longest first
SELECT started_at, area_name, steps, distance_m FROM walk ORDER BY distance_m DESC;

-- Collar battery over time, for comparing against whatever replaces it
SELECT connection_at, battery_percent, signal_percent FROM device_state
ORDER BY connection_at;
```

## What is deliberately not stored

**The raw API responses.** An earlier sketch kept gzipped, de-duplicated
payloads alongside the parsed tables, so that fields we do not parse today could
be mined later. It is not here, because capturing them means threading a tap
through `FiClient` — the one module that holds the account password — and
doubling the surface area of a change whose entire value is that it cannot break
anything.

Everything `FiSnapshot` carries is recorded. What is lost is only what the
parser already discards. Worth revisiting on its own terms; not worth coupling
to this.
