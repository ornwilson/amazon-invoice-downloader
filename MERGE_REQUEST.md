## fix: scope order-id lookup to the current order card, not the whole page

### Problem

`orderid = spans[8].inner_text()` (the original order-id parsing) was already
known broken as of 2026-05-06 — Amazon changed the order-card markup so that
span index no longer holds the order ID.

An earlier fix (on `feat/filename-format`) replaced it with a `.yohtmlc-order-id`
lookup, but queried it from `page` instead of the current `order_card`:

```python
parent_element = page.query_selector(".yohtmlc-order-id")
```

`page.query_selector` returns the *first* match on the entire page, not the
match within the current order being processed. As a result, every order on
a given results page was assigned the same (first) order ID — the exact bug
reported: "all pdfs from the same web page are assigned the first order
number on the page."

### Fix

Scope the lookup to `order_card`, the element already being iterated over:

```python
order_id_parent = order_card.query_selector(".yohtmlc-order-id")
order_id_span = order_id_parent.query_selector("span.a-color-secondary:not(.a-text-caps)")
orderid = order_id_span.inner_text()
```

### Verification

Ran live against a real Amazon account for all of 2026 (96 orders across
multiple pages).

- **Before the fix**: orders sharing a results page had duplicate IDs, e.g.
  three different dates (`20230109`, `20230109`, `20230109`) and totals all
  stamped with the same order number `112-1709731-4625812`.
- **After the fix**: all 96 processed orders had unique order numbers — zero
  duplicates.
