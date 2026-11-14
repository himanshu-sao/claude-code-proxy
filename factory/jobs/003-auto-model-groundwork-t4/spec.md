# Spec — 003-auto-model-groundwork-t4 (context data for two MIDDLE_MODEL ids)

## Goal

`mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash` are configured in
MIDDLE_MODEL, but neither is in `model_contexts_cache.json` (12 entries today). As a result,
`context_manager.get_model_limits` gives them the `(32_000, 4_096)` safe default. Add both ids to
the cache with the values the user decided, `[262144, 32768]`. Then, after the cache loads,
`get_model_limits` returns `(262144, 32768)` for each id and never the default. 262,144 is NVIDIA's
published hosted spec and was not verified live. 32,768 is the repo's own default output cap
(precedent `c5a0b70`) and has no source. The commit message body must state both facts, because
JSON has no comments. README/QUICKSTART wording belongs to the job's docs task, not to this task.

## Approach

Two files are touched, and no `src/` change is needed.

- **`model_contexts_cache.json`** (tracked; read from the CWD at `provider_discovery.py:144`):
  - Append two keys at the end, keeping the existing `json.dump(indent=2)` layout (2-space indent,
    one number per line):
    `"mistralai/mistral-large-4-1t-a52b": [262144, 32768]` and
    `"minimaxai/minimax-m3.1-flash": [262144, 32768]`.
  - Leave the other 12 entries unchanged.
  - If either key already exists at build time (for example, a startup discovery run wrote a
    `(32000, 4096)` fallback, `provider_discovery.py:224-235`), correct it in place. Never
    duplicate a key.
  - Do not touch `MODEL_CONTEXT_LIMITS` or `_BUILTIN_LIMITS`.
- **`tests/test_context_manager.py`**: add a `TestCachedNimLimits` class.
  - **Fixture**: load the real repo cache from `Path(__file__).resolve().parent.parent /
    "model_contexts_cache.json"`. Apply the same filter as `provider_discovery.py:152-154`: keep
    values that are lists of 2 and convert them to tuples. Use `monkeypatch.setattr` on
    `context_manager._DISCOVERED_LIMITS` (the cache data) and on `context_manager._ENV_OVERRIDES`
    (`{}`). The override reset is required because `src/__init__.py` runs
    `load_dotenv(override=True)`, so a developer's `.env` `MODEL_CONTEXT_LIMITS` could otherwise
    leak into the test.
  - **Do not call `run_discovery_and_patch`**. It depends on the CWD, can reach the network, and
    rewrites the cache file.
  - **Shadowing analysis** (`context_manager.py:103-107`): the exact-key check is case-sensitive.
    Any other casing falls through to a loop in insertion order that matches when
    `disc_id in name` or `name in disc_id`. The first hit wins, so an earlier neighbour that is a
    substring of the id would shadow it. No current entry does this:
    - `mistralai/mistral-nemotron` is not a substring of `mistral-large-4-1t-a52b`.
    - Built-in `mistral-nemotron` is not a marker that matches either id.

    A future entry such as `mistralai/mistral-large` would shadow the id, though. The test makes
    the loop run by querying with upper-cased ids against a dict rebuilt with the two targets
    moved to the END. That way every neighbour is tried first.

## Acceptance criteria

1. **Cache contents.** Run
   `uv run python -c "import json,collections as c; p=json.load(open('model_contexts_cache.json'), object_pairs_hook=lambda kv: (c.Counter(k for k,_ in kv), dict(kv))); n,d=p; assert max(n.values())==1 and len(d)==14; assert d['mistralai/mistral-large-4-1t-a52b']==[262144,32768] and d['minimaxai/minimax-m3.1-flash']==[262144,32768]"`.
   It must exit 0. `git diff model_contexts_cache.json` must show no lines removed or changed
   inside the 12 existing entries; only the comma after the last existing entry plus the two
   new keys may change.
2. **Exact lookup.** With the cache loaded by the fixture, `get_model_limits(id)` returns
   `(262144, 32768)` for each id, and the result is `!= (32_000, 4_096)`.
3. **No neighbour shadowing.** Using the reordered dict (targets last), the upper-cased ids (for
   example `"MistralAI/Mistral-Large-4-1T-A52B"`) still return `(262144, 32768)`.
   `get_model_limits("mistralai/mistral-nemotron")` still returns `(128_000, 16_384)`.
4. **Env still wins.** With `_ENV_OVERRIDES` patched to `{"mistral-large-4": (1_000, 100)}`,
   `get_model_limits("mistralai/mistral-large-4-1t-a52b") == (1_000, 100)`, and the MiniMax id
   still returns `(262144, 32768)`.
5. **Suite and format.**
   `uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py`
   passes, including all existing tests. `uv run black --check -l 100 tests/test_context_manager.py`
   and `uv run isort --check tests/test_context_manager.py` pass. The test code stays Python
   3.9-safe.
