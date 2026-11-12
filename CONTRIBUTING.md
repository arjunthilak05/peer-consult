# Contributing

Thanks for helping. Bug reports, fixes and new adapters are welcome.

## Setup

```bash
git clone https://github.com/arjunthilak05/peer-consult && cd peer-consult
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Python 3.11+ is required. The test suite never calls a real model: `tests/fake_cli.py` stands in
for `claude`, `codex` and `agy` and can simulate auth failures, timeouts, malformed output,
isolation breaches, schema errors, flaky tests and conflicting reviews.

```bash
pytest            # all Python tests (about 1 minute)
ruff check .      # lint
```

### Office UI

```bash
cd office-ui
npm ci
npm test                         # Vitest unit tests
npm run dev                      # Vite dev server (point it at a running `peer-consult council office`)
npm run build                    # writes ../peer_consult/office_dist
npx playwright install chromium
npx playwright test              # starts a real office server with fake providers
```

`peer_consult/office_dist/` is committed so that installing from Git ships a working UI. Rebuild
it whenever you change `office-ui/`; CI fails if the committed bundle is stale.

## Ground rules

- **Advisers stay read-only.** Any change to the argv built in `peer_consult/providers.py`, the agy
  hook gate or the child environment must keep every tool disabled, and must update the security
  model section of the README.
- **No silent fallbacks.** An unavailable model or effort is an error, never a downgrade.
- **Backward-compatible `ask`.** Its flags, JSON output and exit codes are a public interface used
  by installed skills.
- **Skills are templates.** Edit `peer_consult/templates/*.tmpl` and the tables in
  `peer_consult/installer.py`. `peer-consult setup` renders them, so never hand-edit installed copies.
- Add a test for every bug fix. Prefer extending `tests/fake_cli.py` over mocking internals.

## Releasing (maintainers)

1. Bump `__version__` in `peer_consult/__init__.py` and add a section to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v1.2.3 && git push origin v1.2.3`.
3. `.github/workflows/release.yml` does the rest:
   - rebuilds the UI and runs the tests;
   - builds the sdist and wheel;
   - publishes to PyPI;
   - creates the GitHub release.

PyPI publishing uses [Trusted Publishing](https://docs.pypi.org/trusted-publishers/). Before the
first release, add a publisher on PyPI with these values:

- project `peer-consult`
- owner/repository: this repository
- workflow `release.yml`
- environment `pypi`

Then create an environment named `pypi` in the GitHub repository settings.
