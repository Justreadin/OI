# UI refresh: 13.5.0

## Design direction
- Replaced the dark olive / gold / futuristic editorial treatment with a restrained near-black, white and neutral-grey interface.
- Uses system UI typography, compact navigation, subtle borders, flatter surfaces and consistent rounded controls.
- Applied a shared visual layer across dashboard, settings, candidate profile, job review and Gmail pages.
- Responsive navigation and grids collapse for mobile.

## Dashboard structure
- Retains the existing information architecture: briefing, attention items, opportunity radar, application workspace and exports.
- Opportunity rows now have clearer hierarchy for employer, title, type, track, location, eligibility signal, fit score and application state.
- Filters remain available in a collapsible panel.
- Opportunity results now have server-rendered pagination (15 per page by default; selectable 10, 15, 25 or 50).
- Pagination preserves search, track, status, opportunity type and view filters.

## Notes and limitations
- Pagination is applied after the current bounded dashboard query and preference qualification. The dashboard currently loads at most 1,000 active jobs into its working set; a future database-native count/offset query is recommended for very large indexes.
- No backend application-generation, approval, email or submission behavior was intentionally changed.
