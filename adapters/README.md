# Writing an adapter

An adapter connects one tracker to the canonical work-item model. The
server, the skills and the conformance suite only ever call the interface
in [base.py](base.py). A new tracker therefore needs a new adapter and a
few lines of wiring, and nothing else changes. This guide covers the
interface, the rules every adapter keeps, and how to prove one.

The two adapters here are the worked examples. [Plane](plane/) sets states
directly and stores an idempotency key natively. [Jira Cloud](jira/) has
neither: states move through transitions, and the key is a label. Read
`base.py` first, then whichever adapter is closer to your tracker.

## Where it sits

```
skills/*/SKILL.md       judgment: what to file, and when to ask
server/mcp_app.py       registers the tools, and nothing else
server/service.py       the conventions: review label, propose → commit, external ids, templates
adapters/<backend>/
  adapter.py            the canonical model in and out, mechanically
  transport.py          the only file that knows the wire
```

## The interface

Subclass `Adapter` and implement every abstract member. The constructor
takes the `BoardConfig`. Both adapters here also take three optional
arguments: `transport` (built from the config when left out; tests pass a
fake), `secret` (default `secrets.get`) and `today` (default
`date.today`, since an iteration's state comes from its dates). Each
refuses a config for another backend with a `ValueError`.

| Member | What it does |
|---|---|
| `capabilities` | A property. Build it from `config.materializations()` and `config.collapse_rules()`, plus the description format (Markdown, HTML or ADF), whether states change through transitions, and whether the tracker stores an idempotency key natively. Skills read it before acting. |
| `describe_board` | Reads the live board: its types, states, labels, members, containers, iterations and the config's custom fields. Checks the config against it and lists every mismatch in `problems`, including a level form the tracker can't realize (Jira reports `container`). Reads only, and caches the result, which is also the write gate ([below](#read-proven-before-write)). |
| `find_items` | Searches. `external_id` is an exact match, the idempotency lookup. `query` is free text. `level`, `state` and `label` narrow the result. `iteration` keeps the items whose *current* iteration it is, a closed one included. |
| `get_item` | One item by its id or its human key, or `NotFound`. |
| `get_iteration` | One iteration by id or name, in the state the tracker reports now, or `NotFound`. |
| `create_item` | Calls `item.check()`, writes the item, and returns it with `id` and `key` filled. It applies the collapse rule for each level the board doesn't materialize, so an initiative or feature named on the item lands as a label, a component or a description line. |
| `update_item` | Applies an `ItemPatch`. `None` leaves a field as it is, a sequence replaces (`labels=()` clears them), and `fields` sets only the fields it names. |
| `add_comment` | Takes Markdown and writes the tracker's own format. |
| `create_iteration` | Find-or-create by name, never a duplicate. `existing_iteration` refuses a found one whose dates differ from those given. An iteration whose dates cover today ends up active; Jira starts the sprint. |
| `move_to_iteration` | Puts the items into the iteration with that id or name. |
| `close_iteration` | Marks the iteration closed. Rollover (close, then move what's left) is composed above the adapter. |

Everything goes in and out as the model's types: `WorkItem`, `ItemRef`,
`Iteration` and `Comment`, from [server/model.py](../server/model.py). A
raw vendor record never leaves the adapter. Descriptions are Markdown;
convert at the edge, as [plane/markdown.py](plane/markdown.py) and
[jira/adf.py](jira/adf.py) do.

`base.py` also holds what both adapters share: the `BoardDescription`
that `describe_board` returns, `field_problems` (custom-field values
checked against the board), `option_names` (option values in the board's
own spelling) and `existing_iteration`.

## The errors

Callers catch `AdapterError`, never a vendor exception, so the transport
maps every failure onto one of these. `detail` carries the vendor's own
message for the operator, and never anything secret.

| Error | Raise it when | Typically |
|---|---|---|
| `AdapterError` | Never directly: it is the base class. | |
| `AuthError` | The token is missing, invalid, or lacks the permission. A `SecretUnavailable` from the secrets boundary becomes one. | HTTP 401, 403 |
| `NotFound` | The item, iteration or project the call named doesn't exist. | HTTP 404 |
| `ValidationError` | The tracker rejected a write: its shape, a business rule, the hierarchy, a closed iteration. | other 4xx |
| `RateLimited` | The tracker asked to slow down. It is safe to retry later. | HTTP 429 |
| `Blocked` | An edge wall answered instead of the API, such as Plane's Cloudflare challenge, an HTML page. Not a retry-now case. | |
| `TransportError` | A network failure, a timeout, a 5xx, or an answer that can't be read. | 5xx |
| `Unsupported` | The board can't realize this operation for this level or field. Raise it rather than drop information. | |
| `ConfigMismatch` | The write gate: `BoardDescription.check()` raises it, with every problem, before any write. | |

The class matters. The service turns each error into an instruction for
the agent (`_explain` in [server/service.py](../server/service.py)): a
`RateLimited` says to wait and retry, and an `AuthError` says retrying
won't help. The conformance runner stops, rather than fails, on
`RateLimited` and `Blocked`, so a re-run resumes.

## Mechanical, not clever

An adapter translates; it doesn't decide. Behavior that would be the same
on every tracker lives in [server/service.py](../server/service.py):

- adding the review label to a new item (the adapter writes the labels
  it is given);
- composing the `external_id` from the intake record;
- propose, then commit with a 30-minute token, and finishing a commit
  that a failed attempt left half done;
- title-case warnings and filling templates;
- choosing the board when one server serves several;
- one tracker call at a time: the service holds a lock, so an adapter
  needn't be thread-safe.

The adapter owns what is specific to its tracker: resolving names to ids,
applying the collapse rules, storing and finding the idempotency key, and
the vendor's quirks (Jira's transitions, Plane's trailing slashes, a
project time zone's day edges). If two trackers would need the same code,
it belongs above the adapter.

## Rules every adapter keeps

### No delete path

No method deletes, and no request is a DELETE. Work ends as `done` or
`cancelled`. Moving an item to another container adds the membership
rather than removing the old one. [tests/test_adapter_guide.py](../tests/test_adapter_guide.py)
fails on a DELETE in any adapter's source, and the conformance suite's
`no-delete` case counts the requests a live run sent.

### Read-proven before write

- **The write gate.** Every write first takes the cached
  `describe_board()` result and calls `.check()`, which raises
  `ConfigMismatch` while the config doesn't fit. Both adapters do this in
  `_ready()`. Reads need only the lookup tables.
- **Refuse before the first call.** Check everything a write needs (the
  item's `check()`, its labels, members and `field_problems`) before
  sending anything, so a write doesn't land half done.
- **Prove the vendor with a read first.** Before a write depends on how
  the API behaves, a dated, GET-only script in [probes/](../probes/)
  reads it. Write-side questions become conformance cases, run against a
  throwaway project. Each adapter's docstring cites the probe or run
  behind its rules.

### Idempotency

A retried commit must find what an earlier attempt made.
`find_items(external_id=…)` is an exact lookup. Plane stores
`external_id` on the item. Jira has no such field, so its adapter writes
the label `xid:<external_id>`, hides it from `WorkItem.labels`, and
remembers the issues this process created, because Jira's search lags.
`create_iteration` looks for the name before it creates.

### Secrets

The token comes only through [server/secrets.py](../server/secrets.py):
`secrets.get(token_env)`, called on the first request, never at
construction. It never appears in a message, a `detail` or a log.

### Standard library only

The adapters use `urllib` and `json`. The one runtime dependency, the
`mcp` SDK, belongs to the server.

## The transport

One file per backend knows the wire: the base URL, the auth headers, the
User-Agent, pacing, paging and the error mapping. The adapter sees only
this protocol, so tests can hand it a fake:

```python
def request(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any: ...
def get_all(self, path: str, params: dict | None = None) -> list[Any]: ...
```

- Pace the calls `throttle` seconds apart. Plane's default is 1.5 and
  Jira's is 0.5.
- Append each request's `(method, path)` to `log` as it goes out. The
  conformance suite's no-delete count reads it.
- Map every failure onto the taxonomy in one place (`_map_http_error` in
  both transports).

## Proving it

### Offline: a fake transport

`tests/fake_<backend>.py` has the transport's shape, with a route table
keyed `"METHOD path"`. Writes create records, so a create reads back.
`fail` maps a route to the exception it raises, and `calls` logs every
request. Build the shapes from the probe's evidence. When a live run
finds something the fake didn't model, fix the fake and add a test;
[conformance/README.md](../conformance/README.md) lists each one so far.
Ids are made up and never random (version 4) UUIDs:
[tests/test_public.py](../tests/test_public.py) refuses those, along with
token-shaped strings.

`tests/test_<backend>_adapter.py` covers the adapter against the fake,
and [tests/test_conformance.py](../tests/test_conformance.py) runs the
whole conformance suite against it. `uv run pytest` never touches the
network.

### Live: the conformance suite

`conformance/<backend>.py` gives the suite two functions:

- `make_adapter(config, *, throttle, today)` returns the adapter on a
  real transport, plus a function returning that transport's log;
- `provision(ctx)` gets a fresh throwaway project ready. It creates what
  the API can, and raises `NeedsOperator` naming what a person must do
  in the tracker's UI.

The cases themselves are backend-agnostic
([conformance/cases.py](../conformance/cases.py)). Run them with
`--dry-run` first, then live against a **throwaway** project: the suite
writes, and never deletes. Add the dated result to
[conformance/README.md](../conformance/README.md#results). A tracker is
supported once its adapter passes live.

## Wiring checklist

| Where | What to add |
|---|---|
| `server/config.py` | A `Backend` member and its `CONNECTION_KEYS`, plus any extra check, such as Jira's `user_env`. `generic` is accepted but has no adapter; give the new tracker its own member. |
| `adapters/<backend>/` | `transport.py`, `adapter.py`, an `__init__.py` exporting the adapter, and a `__main__.py` with the read-only `describe` command (copy Plane's). |
| `server/__main__.py` | A branch in `make_adapter`. |
| `conformance/<backend>.py` | `make_adapter` and `provision`. |
| `conformance/__main__.py` | An entry in `HARNESSES`. |
| `conformance/runner.py` | The provisioner, in `cases_for`. |
| `tests/` | The fake, the adapter's tests and an offline conformance run. |
| `examples/boards/` | `<backend>.example.toml`, with every key commented. `tests/test_config.py` loads each example. |
| `README.md` | The backend in the board config's `backend` row and its connection table. |
