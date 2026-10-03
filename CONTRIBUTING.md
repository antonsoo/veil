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

To exercise the optional spaCy backend:

```bash
uv sync --locked --group dev --extra spacy
uv run --no-sync pytest tests/test_backends_spacy.py
```

These tests load a real spaCy pipeline with synthetic entity rules; they
need no downloaded language model and do not measure NER accuracy. The CI
job runs them on Python 3.10 and 3.14.

The project's uv configuration prefers stable dependency releases. Use
`uv sync --locked` to reproduce the committed lock; opt into prereleases
explicitly only when testing them.

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

## Community and private reports

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Anton Soloviev
maintains this project and handles conduct reports at
[anton@praviel.com](mailto:anton@praviel.com).

Use the bug or improvement forms for public issues. For a suspected security
vulnerability or a conduct concern, email the maintainer privately with the
repository name and relevant details. Do not post credentials, personal data,
private logs, or confidential documents in a public issue.
