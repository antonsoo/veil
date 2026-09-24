# Contributing

veil is a young project; issues and PRs are welcome.

## Setup

```bash
git clone https://github.com/antonsoo/veil
cd veil
uv sync --group dev
```

## Workflow

```bash
uv run pytest              # tests (add Hypothesis property tests for anything
                            # touching the streaming restorer)
uv run ruff check .         # lint
uv run ruff format .        # format
uv run mypy                 # typecheck (strict)
```

All four must pass before a PR is merged; `.github/workflows/ci.yml` runs
the same checks.

## Adding a detector

Detectors live in `src/veil/detectors/`, implement the `Detector` protocol
(`name: str`, `find(text: str) -> list[Entity]`), and should be pure
functions of their input. Add the detector to `default_detectors()` (or
`all_detectors()` if it's a heuristic best left opt-in, like the address
detector) in `src/veil/detectors/__init__.py`, and add focused tests
covering true positives, true negatives, and edge cases in
`tests/test_detectors_<name>.py`. If there's an independent oracle for
correctness (a checksum, a published test vector), use it.

## Adding a name/org/location backend

Implement the `NameBackend` protocol in `src/veil/backends/base.py`. State
any accuracy numbers you report, and how you measured them — see the
`SpacyBackend` docstring for the level of honesty expected.

## Web demo

```bash
cd web
npm install
npm run dev      # copies src/veil into public/veil-src.json, then serves the demo
npm run build    # typecheck + production build to web/dist
```

The demo (`web/`) runs the real package via Pyodide — if you change
detector/masker/restore behavior, the demo picks it up automatically on
the next build; there's no separate JS logic to keep in sync.

## Commit style

Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
