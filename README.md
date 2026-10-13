# kervan-search

> Part of **[Kervan](https://github.com/onurkoocc/kervan-system)**, a fictional cargo company built as a
> reference for backends where AI agents can safely act on a customer's behalf. Start there.

Knowledge base search for Kervan, a fictional cargo and delivery company. It
serves short help articles to `kervan-mcp`'s `search_help` tool. All content is
synthetic. The shared contract for every Kervan repository is the system
`SPEC.md` (§7 for this service).

## API

The committed contract is [`docs/openapi.json`](docs/openapi.json) (interface
`SearchApi`).

| Request | Answer |
|---|---|
| `GET /search?q=<text>&k=<1..10>` | `{"results": [{"id", "title", "snippet", "score"}]}`, best first |
| `GET /health` | `{"status": "ok"}` |

- `k` defaults to 3. A `k` outside 1..10 or not an integer gets a 422. A
  missing or empty `q`, or one longer than 500 characters, gets a 422 too.
- Only articles with a positive score are returned, so a query with no known
  words gives `{"results": []}`. Ties are ordered by article id.
- Scores are cosine similarities rounded to 4 decimals.
- The snippet is the article paragraph that shares the most words with the
  query, cut to 200 characters.
- If the vector provider fails, the answer is 502
  `{"error": "provider_unavailable", "message": …}`.
- A request may carry `X-Trace-Id` (1–64 letters, digits or `-`). It is logged
  and echoed back. Without one, the service generates an id.

## Knowledge base

`data/kb/*.md` are the articles. Each one starts with front matter holding
exactly `id` and `title`; the id matches the file name. Paragraphs are
separated by blank lines. Articles are loaded and indexed at start. A malformed
article, a duplicate id or an empty directory stops the service.

## Vector providers

`VectorProvider` (`src/kervan_search/providers.py`) has two methods:
`index(docs)` and `query(text, k)`.

- **`SimulatedProvider`** (`VECTOR_PROVIDER=simulated`, the default). Hashed
  bag-of-words embeddings, with BLAKE2b buckets, tf-idf weights and L2
  normalization, ranked by cosine similarity. It does not use Python's salted
  `hash()`, so the same corpus and query score the same on every machine and
  in every process. `tests/test_determinism.py` pins the values.
- **`HttpProvider`** (`VECTOR_PROVIDER=http`). It calls an external vector
  search API with httpx. Kervan does not use it. Its protocol:
  - `POST {VECTOR_PROVIDER_URL}/v1/index` with
    `{"documents": [{"id", "text"}]}` at start;
  - `POST {VECTOR_PROVIDER_URL}/v1/query` with `{"query", "top_k"}`, which
    answers `{"matches": [{"id", "score"}]}`.

  `VECTOR_PROVIDER_API_KEY`, when set, is sent as a Bearer token. The tests
  run it against `httpx.MockTransport`.

## Configuration

All configuration comes from the environment, and the defaults are the
compose values.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8001` | Listen port |
| `LOG_FILE` | unset | Also append each log line to this file |
| `VECTOR_PROVIDER` | `simulated` | `simulated` or `http` |
| `VECTOR_PROVIDER_URL` | unset | Base URL of the external provider; required for `http` |
| `VECTOR_PROVIDER_API_KEY` | unset | Optional Bearer token for the external provider |

An invalid configuration is refused at start, with exit code 2.

## Logs

The service writes JSON lines to stdout, and also appends them to `LOG_FILE`
when it is set. Example:

```json
{"ts":"2026-10-09T12:00:00.000Z","level":"info","service":"search","msg":"request","trace_id":"…","method":"GET","path":"/search","status":200,"duration_ms":2,"k":3,"results":3}
```

Requests log `info` for a 2xx or 3xx answer, `warn` for 4xx and `error` for
5xx. The query text is never logged, because customers may type personal data
into it.

## Development

The commands below are for Windows; on Linux or macOS, use `.venv/bin/python`
instead of `.venv/Scripts/python`.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python -r requirements-dev.txt
.venv/Scripts/python -m pytest
PYTHONPATH=src .venv/Scripts/python -m kervan_search   # serves on :8001
```

Without uv: `python -m venv .venv` and `pip install -r requirements-dev.txt`.

**After changing the API**, regenerate the contract and commit it.
`tests/test_openapi.py` fails while it is stale.

```sh
PYTHONPATH=src .venv/Scripts/python -m kervan_search.openapi
```

**Dependencies.** The lock files `requirements.txt` (runtime) and
`requirements-dev.txt` (tests) are fully pinned and hashed. They are compiled
from `requirements.in` and `requirements-dev.in`:

```sh
uv pip compile --universal --python-version 3.12 --generate-hashes -o requirements.txt requirements.in
uv pip compile --universal --python-version 3.12 --generate-hashes -o requirements-dev.txt requirements-dev.in
```

## Docker

```sh
docker build -t kervan-search .                        # the service, non-root, port 8001
docker build --target test -t kervan-search:test .     # runs the tests in the image
docker run --rm -p 8001:8001 kervan-search
```

Dependencies are downloaded as wheels only (`pip download --only-binary=:all:`),
in a stage that sees only the lock file. Installing, testing and running all
happen in `RUN --network=none` steps (SPEC §11).
