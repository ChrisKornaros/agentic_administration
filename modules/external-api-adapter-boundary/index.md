---
name: external-api-adapter-boundary
type: guardrail
scope: repo
lifecycle: experimental
dependencies: []
evidence:
  - playbook/03-design-patterns.md#the-seven-patterns
  - tools-stack/web.md#patterns-to-keep-framework-agnostic
applies_when:
  - project integrates ≥1 third-party API or SDK (payments, social platforms, LLM providers, storage)
version: 1
---

# Wrap each external API behind an adapter — depend on your interface, not their SDK

## Rule

Every third-party API or SDK gets a thin adapter module that exposes
an **internal, project-shaped interface**; the rest of the codebase
depends on that interface, never on the vendor SDK directly. The
adapter is the only place that imports the vendor library, knows its
auth dance, maps its error types to the project's, and translates its
payloads to/from the project's own models. When a second platform
(or a vendor's v2 API) shows up, it implements the same interface —
callers don't change.

## Why

This is the "thin routes, thick services" / framework-agnostic
service-layer pattern
([../../playbook/03-design-patterns.md §The seven patterns](../../playbook/03-design-patterns.md#the-seven-patterns),
patterns 1 and 4), pushed out to the *vendor* edge: the same way a
web route shouldn't carry business logic, application code shouldn't
carry vendor-SDK shapes. The repo already states the
auth-specific corner of this — "no hand-rolled auth; use a proven
library"
([../../tools-stack/web.md §Patterns to keep, framework-agnostic](../../tools-stack/web.md#patterns-to-keep-framework-agnostic)) —
the adapter boundary generalizes it: a proven library is fine, but
it lives behind your interface so swapping or upgrading it isn't a
codebase-wide edit.

The `content_manager` project is the forcing case. It publishes to
YouTube, Instagram, and TikTok, each with a different SDK, auth model,
and quirk (TikTok is upload-as-draft, not direct-post). Building it
"vertically, one platform at a time" only works if each platform sits
behind a shared publish interface; otherwise the YouTube-specific
shape leaks into the scheduler, the DB layer, and the website-embed
step. The website integration is itself an adapter (a `site/` module
that edits a local Quarto clone, commits, and pushes) over the same
boundary — proof the pattern isn't social-media-specific.

## How to apply

- **Adding an integration:** create `adapters/<vendor>.py` (or a
  package) that imports the SDK and exposes verbs in the project's
  language — `publish(post) -> PublishResult`, not
  `youtube.videos().insert(...)`. Callers import the adapter, not
  `googleapiclient`.
- **Define the interface from the project's needs, not the vendor's.**
  The method signatures describe what *your app* does ("publish a
  recipe video"), so a second vendor can satisfy them. If you find
  yourself naming methods after the vendor's endpoints, the boundary
  is in the wrong place.
- **Map errors at the boundary.** The adapter catches vendor
  exceptions and raises the project's own (`PublishRejected`,
  `RateLimited`) so callers never `except googleapiclient.HttpError`.
- **Secrets enter here.** The adapter is the consumer of the
  [[secrets-no-plaintext]] boundary — it asks `secrets.get(...)`; the
  rest of the code asks the adapter.
- **Tests target the interface.** Because callers depend on your
  interface, tests inject a fake adapter — which is exactly what
  [[no-live-external-in-tests]] requires, and the adapter boundary is
  what makes it cheap.

## Anti-patterns

- `import stripe` (or `googleapiclient`, `instagrapi`, …) in a route
  handler, a model, or the scheduler. The vendor is now welded to
  that layer.
- An "adapter" whose methods mirror the vendor's endpoints 1:1
  (`create_media_container`, `publish_media_container`). That's a
  passthrough, not a boundary — the vendor's shape still dictates
  your callers.
- Catching vendor exception types outside the adapter. A vendor
  library upgrade that renames an exception now breaks call sites.
- One giant `integrations.py` that branches on `if platform ==
  "youtube"` internally. Each platform is its own adapter behind the
  shared interface; the dispatch lives above them, not inside one
  file.
- Returning the vendor's raw response object to callers. Translate to
  a project model so the response schema isn't a hidden dependency.

## Related

- [[secrets-no-plaintext]] — the adapter is where credentials are
  read; the two boundaries stack.
- [[no-live-external-in-tests]] — the adapter interface is the seam
  tests substitute at; this module is what makes that substitution
  clean.
- [[duckdb-default-store]] — the persistence boundary's sibling; both
  keep an external dependency (a DB engine, a vendor API) from
  spreading through the codebase.
