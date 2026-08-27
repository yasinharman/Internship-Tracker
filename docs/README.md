# Documentation

Four kinds of thing live here, and the distinction matters when you are
deciding where to write something down.

| | |
|---|---|
| [sites/](sites/) | **Measurements.** One file per job board: the selectors, the filter ids, what was tried and what it returned, with dates. Nothing in here is a plan - it is a record of what the site did when someone looked. |
| [pipeline.md](pipeline.md) | What happens to a posting after it is stored: dedupe, notify, classify, and the still-open check. Each section carries the evidence its rule was written from. |
| [dashboard.md](dashboard.md) | The board itself - the API, the front end, and the rules about which rows a reader is shown. |
| [design/](design/) | Where the dashboard's look came from: the reference mockup and two marked-up screenshots. Referenced from `dashboard.md` and from the header comment in `web/src/pages/DashboardPage.tsx`. |

## The rule these files exist to serve

A number in a spider - `FIELD_FILTER = ["25"]`, `GEO_ID = "90010422"`,
`f_E=1` - is unmaintainable without a record of where it came from. The habit
is: measure, then write down the measurement WITH ITS DATE, then write the
code. When a site changes, the note is what tells you whether the new
behaviour is new or whether the original reading was wrong.

Reversals stay in the files rather than being deleted. LinkedIn's entry still
opens with the 27.07.2026 argument for dropping it, because that argument was
not wrong - only one of its premises changed.
