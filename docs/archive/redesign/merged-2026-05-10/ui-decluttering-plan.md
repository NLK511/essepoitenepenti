# UI Decluttering and Navigation Redesign

**Status:** active redesign reference

## Purpose

This doc defines the next UI/UX pass for the operator workspace.

The current app is functional, but the journey is harder to follow than it should be:
- too many pages compete for attention
- summary, filters, diagnostics, and raw tables are often shown together
- mobile layouts shrink desktop patterns instead of reshaping them
- the user must already know where to go before the app becomes easy to use

This redesign does **not** change product behavior. It changes how the product is presented and how operators move through it.

## Design goals

1. **Make the main journey obvious**
   - The app should guide the operator from overview to action to deep review.

2. **Reduce clutter**
   - Show only the highest-value information by default.
   - Push diagnostics, raw records, and secondary comparisons behind explicit interaction.

3. **Work well on mobile**
   - Mobile should be a deliberate layout, not a compressed desktop copy.

4. **Preserve operator confidence**
   - Do not hide degraded states, warnings, or provenance.
   - Simplify presentation without weakening transparency.

5. **Keep the app fast to scan**
   - The first screen should answer: what changed, what is healthy, what needs attention, what should I open next?

## Primary operator journey

The default journey should read like this:

1. **Monitor**
   - open the dashboard
   - check health, attention items, freshness, and recent activity

2. **Review**
   - open plans, signals, context, or runs only when something needs a decision

3. **Investigate**
   - drill into a single item when something is degraded, surprising, or suspicious

4. **Tune**
   - open research only when the operator is evaluating performance or changing settings

5. **Administer**
   - use jobs, watchlists, settings, and logs for setup and maintenance

## Information architecture

The workspace should feel like four grouped modes:

### 1. Monitor
Pages that answer “is the system healthy and what needs attention?”
- Dashboard
- Jobs overview
- Watchlists overview
- Context freshness indicators when relevant

### 2. Review
Pages that answer “what happened and what should I inspect?”
- Ticker signals
- Recommendation plans
- Broker orders
- Run detail
- Context review

### 3. Research
Pages that answer “how well is the system working and what should change?”
- Research home
- Recommendation quality
- Decision samples
- Signal gating tuning
- Plan generation tuning

### 4. Admin / Reference
Pages that support setup and maintenance:
- Settings
- Docs
- Debugger
- Worker logs

## Layout principles

### A. One page, one primary question
Every page should have a single obvious job.

Examples:
- Dashboard: “what needs attention now?”
- Recommendation plans: “which plans deserve review?”
- Research: “is the system improving?”
- Settings: “what operational defaults are active?”

### B. Summary first, detail on demand
Each page should follow the same structure where possible:
1. page header
2. key metrics or summary state
3. primary chart or table
4. secondary analysis in collapsible or lower-priority sections
5. raw detail only when needed

### C. Filters should be lightweight
Filters should not dominate the page.
Prefer:
- one compact filter bar
- sticky when useful
- collapsible on mobile
- only the filters that materially change the page

### D. Use progressive disclosure
If a section is only useful to a smaller subset of users, it should be:
- collapsed by default, or
- moved behind a secondary tab, or
- opened through a drill-down page

### E. Preserve provenance and warnings
Simplification must not remove:
- source details
- warning states
- degraded-input indicators
- confidence caps
- evaluated-vs-resolved distinctions

## Mobile rules

Mobile should intentionally reshape the page.

### Navigation
- Use a small number of top-level destinations.
- Prefer grouped sections over long flat menus.
- Keep the current section obvious.
- Avoid deep link sprawl in the primary nav.

### Page headers
- Keep the title and one-line subtitle.
- Avoid long explanatory subtitles on every page.
- Use actions sparingly.

### Metrics
- Use stacked cards instead of dense metric grids.
- Limit the number of headline metrics shown at once.
- Keep only the most decision-relevant metric visible at the top.

### Tables
- Convert wide tables to card stacks or condensed rows on small screens.
- Keep only the most important columns visible by default.
- Move secondary columns into expandable details.

### Filters
- Collapse filters into a drawer, accordion, or select-first pattern.
- Do not let a filter strip consume the first screen.

### Actions
- Keep one primary action per screen whenever possible.
- De-emphasize secondary actions.
- Avoid many equal-weight buttons in the header.

### Typography and spacing
- Reduce simultaneous emphasis.
- Increase breathing room between sections.
- Avoid cramming multiple concepts into a single row.

## Page-specific simplification priorities

### 1. Dashboard
Current problem:
- too much status is visible at once
- the page mixes alerting, trend context, and performance detail

Desired state:
- top summary cards
- one clear “what needs attention” area
- one trend area
- collapsible supporting diagnostics

### 2. Recommendation plans
Current problem:
- the page mixes review, analytics, and long-form detail

Desired state:
- plans list first
- selected-plan detail second
- advanced analytics behind a secondary section or tab

### 3. Research
Current problem:
- too many research surfaces compete on one screen

Desired state:
- research home as a hub
- each research task gets a clear subpage
- avoid giant mixed-purpose pages

### 4. Ticker signals
Current problem:
- dense candidate lists and many supporting fields

Desired state:
- cleaner triage list
- compact controls
- detail shown only after selecting a ticker or expanding a card

### 5. Context review / context detail
Current problem:
- snapshots and raw context can overwhelm the operator

Desired state:
- summary of the current backdrop first
- source/event detail second
- raw detail available but not dominant

### 6. Broker orders / run detail / debugger
Current problem:
- diagnostic power is useful, but not all details are equally important

Desired state:
- status and impact first
- payloads and logs folded into details
- easier scanning for failed or unusual rows

## Recommended implementation sequence

### Phase 0 — spec and measurement
- update UX/spec docs
- define the canonical page hierarchy
- identify clutter-heavy components and mobile pain points
- decide which views become summary-first and which become drill-down only

### Phase 1 — shared shell cleanup
- standardize page headers
- standardize filter placement
- standardize section spacing and card density
- make the mobile nav easier to use

### Phase 2 — high-traffic page simplification
- dashboard
- recommendation plans
- ticker signals
- research home

### Phase 3 — detail-page compression
- broker orders
- run detail
- context review/detail
- debugger
- worker logs

### Phase 4 — polish and consistency
- table/card responsive behavior
- action button consistency
- empty states and loading states
- doc alignment with the shipped UI

## Success criteria

The redesign is moving in the right direction if:
- the dashboard answer is obvious within a few seconds
- mobile users can reach the main tasks without hunting
- filters no longer dominate the first screen
- detail pages still preserve warnings and provenance
- the operator can tell what to do next without already knowing the app

## Non-goals

This redesign does not:
- change recommendation logic
- change execution logic
- change scoring semantics
- remove diagnostic depth
- hide degraded states
- collapse important distinctions between effective, broker, and phantom results

## See also

- `README.md`
- `principles.md`
- `target-architecture.md`
- `../operator-page-field-guide.md`
- `../user-journeys.md`
- `../roadmap.md`
