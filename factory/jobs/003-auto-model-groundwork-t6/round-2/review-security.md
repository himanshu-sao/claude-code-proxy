VERDICT: PASS

Scope: `git diff 11b8f2a HEAD -- README.md QUICKSTART.md .env.example src/`, read in the worktree and checked against src/__init__.py, src/core/config.py, src/api/endpoints.py, src/api/compat.py, src/core/signal_log.py and src/core/logging.py. `import src` resolves inside the worktree. I ran small snippets under $TMPDIR only (no real log file, no server, no port). No blocking finding. The non-blocking notes below are optional wording.

1. Finding 1 (open-proxy warning) is fixed and true.
   - Placement: it is the first paragraph of the README signal-log section (README.md:338). It is also in the Features bullet (README.md:14), the `AUTO_SIGNAL_LOG` env bullet (README.md:107), `.env.example:58-63` beside the signal-log variables, and QUICKSTART.md:54.
   - HOST in `.env`, not on the command line: correct. `src/__init__.py:8` calls `load_dotenv(override=True)`, `config.py:38` defaults `HOST` to 0.0.0.0, and `.env.example` ships `HOST="0.0.0.0"` uncommented. README.md:338 says the command-line form fails "while `.env` sets `HOST`", which is exact.
   - Public placeholder: README.md:338 and `.env.example:60-62` tell the operator to use a private random value, and the placeholder is the one at `.env.example:6`. Correct.
   - Key coverage: `validate_api_key` is a dependency only on `POST /v1/messages` (endpoints.py:100) and `POST /v1/messages/count_tokens` (endpoints.py:209). `/health` (246), `/test-connection` (290), `/v1/models` (330) and `/` (404) have none. The claim holds for the four endpoints it names.
   - Non-blocking nit: "only protects" is slightly too narrow. The desktop-compat routes in src/api/compat.py (`/v1/me`, `/api/organizations...`, and others) also call `validate_api_key` through `_compat_auth`. It errs toward caution and none of those routes can reach the signal log, so I am not asking for a change. If the sentence is touched again, "among the endpoints it names, only..." would be exact. `/api/hello`, `/hello` and the catch-all are unauthenticated too.

2. Finding 2 (privacy wording) is fixed. It does not over-claim, and it does not under-claim against signal_log.py.
   - "content-free" and "never message text" are gone from README.md, QUICKSTART.md and `.env.example`. The remaining wording is "no raw message text or header values" (README.md:14) and "no message, system, tool or header values" (README.md:345).
   - The unsalted 8-hex hashes, the 32-bit size, and the guessing risk are all stated. `signal_log.py:117-119` is a SHA-256 over a constant prefix plus the text, cut to 8 hex characters, so it is unsalted and 32-bit. README.md:345 and `.env.example:52-56` say the same. The Features bullet says "unsalted" and points to the section.
   - Verbatim names: README.md:345 states the `[A-Za-z0-9_.:/-]{1,64}` rule and the "other" fallback, and says a key-like string used as a name (model, header, key) would be kept. This matches `_NAME_RE` and `_safe_name` (signal_log.py:43, 91-95).
   - The `fm_hash` order (reminders removed, then whitespace normalised, then cut to 512 characters) matches `_first_message_hash` (signal_log.py:195-226).
   - The README does not contradict the code. The record also holds the integers `max_tokens`, `think_budget`, `est_tokens` and `msgs`. These fall under "counts", and none carries content.
   - Non-blocking, outside this diff: the docstring at `signal_log.py:246` still says "Build the content-free record". It is a source comment, not user-facing, and the rework note ruled out code edits.

3. Finding 3 (retention) is fixed, and the arithmetic and advice are correct.
   - README.md:346 and `.env.example:64-67` say to turn the switch off and restart first, then delete `logs/auto_signal.log*` including the rotated files.
   - Why this order works: the handler is built with `delay=True` but then keeps its stream open. Deleting the file under a running proxy would leave it writing to an unlinked file. A restart with the switch off also stops a new file being created.
   - Arithmetic: the clamps are `_MAX_BACKUP_COUNT = 20` and `_MAX_MAX_BYTES = 1073741824` (signal_log.py:30-31). That gives (20 + 1) x 1 GiB = 21 GiB. I computed it as 21.0. The defaults give (3 + 1) x 5 MiB = 20 MiB, which matches "about 20 MB".
   - "A peer can drive it when the proxy is open" is consistent with the open-proxy analysis in item 1.
   - Nit: if an operator exports `AUTO_SIGNAL_LOG=1` in the shell and also removes the line from `.env`, the shell value still applies. The docs already say `.env` only overrides keys it contains. I am not asking for a change.

4. The strict-umask sentence in the File mode bullet (README.md:347) is accurate.
   - Where `fchmod` exists the file is exactly 0600 whatever the umask: `_open` does `os.open(..., 0o600)` then `os.fchmod(fd, 0o600)` (signal_log.py:343-347). I confirmed the mode is `0o600` with umask 022. Without `fchmod`, `0o600 & ~umask` can only be stricter, which is what the text says.
   - The directory claim is true. With `os.makedirs(mode=0o700)` (signal_log.py:367), umask 0277 gave a directory of mode 0o500, which is non-writable. Umasks 022 and 077 gave 0o700. Write failures go to `handleError`, which logs at DEBUG only.
   - The doc's hedge "if the module itself had to create the directory" is right. `src/core/logging.py:34` already creates `logs/` with default modes at import, so the module normally never creates it.
   - "An existing `logs/` directory keeps its mode, do not assume it is 0700": true, and it is the safe direction.

5. No new problems from the rework.
   - No insecure advice. Loopback binding and a private key are recommended, the placeholder is flagged as public, and the doc stays honest that this is "a local, single-operator run".
   - Key-like strings: I scanned the added lines for token-shaped strings and long random runs. None found. The only mentions are the key prefixes, described in prose with no characters following. `your-expected-anthropic-api-key` is the existing placeholder, quoted to warn against it. The pre-existing command-line `NVIDIA_API_KEY` example at README.md:~383 is unchanged and was non-blocking in round 1.
   - src/conversion/effort_mapper.py: `git diff --stat 11b8f2a HEAD -- src` shows only that file (11 insertions, 5 deletions). Its AST with docstrings stripped is identical to `11b8f2a` (checked, prints True), so it is docstring-only.
   - No dependencies were added.
