# Live verification of the desk interface, 2026-10-30

Not a test run: a person-shaped journey driven through a real browser against a
real backend, to check that the interface does what the API tests say the API
does. Nothing here touched production.

## Environment

* Backend: Django 5.2.18 from this branch, SQLite, a throwaway database seeded
  with one company, one manager (`dev_mgr`), one **specialist** (`dev_spec`),
  one platform admin (`dev_admin`) and one published knowledge article.
* Frontend: the production build (`next build` + `next start`) of this branch,
  reaching Django through the new `KG_DEV_API_PROXY` rewrite so the browser
  sees the same same-origin `/kg-api` shape as production. The dev server is
  not usable for this: its HMR socket is refused by the project's own CSP
  (`connect-src 'self'`) and the page never hydrates.

## What was done, in the browser, as the specialist

A specialist, not a manager — the seat that got a 403 everywhere before this
work and therefore had only the telephone.

1. Found **پشتیبانی و درخواست‌ها** in the sidebar and opened `/requests`.
2. Filed a ticket. The kind dropdown offered **only پشتیبانی**: the commercial
   kinds are absent for this seat because the list comes from the server's
   `meta`, not from a constant in the frontend.
3. The ticket showed `پاسخ اول: در مهلت، در انتظار`, `رسیدگی: در مهلت، در انتظار`
   and `۲ روز مانده` — the normal-priority 48 h resolution target.
4. The admin replied, added an **internal note**, and completed the ticket.
   Server state afterwards: `first_response_at` stamped, response SLA `met`,
   `assignee` set, `handled_by = dev_admin` (the acting admin, not the literal
   string `admin`).
5. Back in the customer's view the thread showed **two** messages — the
   internal note is not served to the customer. Screenshot:
   `customer-ticket-thread.jpg`.
6. The customer rated the resolution 5/5 through the faces; the page then read
   `امتیاز شما ثبت شده است: ۵ از ۵`.
7. On `/browse`, the feedback widget sent `4` plus a comment. It arrived in the
   admin feed as `/browse · 4 · «جستجو روی منوال‌های بلند کند است.»` and did
   **not** appear in the support queue.
8. The help panel searched the knowledge base, found the seeded article under
   **دانش‌نامهٔ پشتیبانی**, opened it, and took a 👍.
9. A search for `ظرفیت روغن گیربکس` found nothing — and appeared in the metrics
   as `top_misses: [{query: 'ظرفیت روغن گیربکس', count: 1}]`.
10. In the admin panel: the KPI section rendered the whole journey
    (`admin-support-kpis.jpg`); **بازبینی شد** cleared the article's
    "needs review" badge **without** bumping its version; and the closed ticket
    was promoted into a draft article, which came back owned by `dev_admin`
    with `source_request = 1` and the internal note excluded from its text.

## The numbers that journey produced

`support-metrics-after-live-journey.json` is the untouched response of
`GET /api/admin/support/metrics/?days=30` at the end of it (only
`generated_at` removed, so two runs diff cleanly). Every figure in it comes
from the steps above.

## Defects this verification found and fixed

| What | Fix |
|---|---|
| The CSAT score rendered as a Latin `5` beside a Persian `۵` | `faNum()` in `RequestsView` and `RequestsInbox` |
| A promoted draft opened with the ticket's first paragraph twice — once as the question, once as the first line of the conversation | `api/knowledge.promote_request_view` skips the message that merely repeats the body; pinned by `test_the_draft_does_not_repeat_the_opening_paragraph`, which fails on the previous code |
| `/requests` was unreachable for a specialist: the sidebar link was manager-only | the support link is its own group, shown to every seat |

## Limits of this evidence

* A seeded local database, not production data.
* One person, one browser, one pass. It is a demonstration that the journey
  works, not a test suite — `qa/e2e/tests/support.spec.js` is the repeatable
  form, and it has not been run here because it needs the seeded QA stack.
* No accessibility scan of the new surfaces yet (`qa/e2e/tests/a11y.spec.js`
  covers four public pages only).
