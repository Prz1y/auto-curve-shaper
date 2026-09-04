# Contributing to Auto Curve Shaper

Thanks for your interest in contributing! This project is licensed under
**GPL-3.0-or-later** — by submitting a contribution you agree to license
your work under the same terms.

其他语言 / Other language: [中文版](../zh/CONTRIBUTING.md)

---

## Ways to contribute

### 🐛 Reporting bugs

Before filing:

1. Search existing issues
2. Confirm you're on the latest version
3. Collect: CPU model, Windows version, Python version, logs from `logs/`,
   and `state.json` if relevant

Include a clear title, reproduction steps, expected vs actual behavior, and
log excerpts.

### 💡 Feature requests

Describe the use case and expected benefit. Hardware-behavior features
should state what was *measured* (frequencies, WHEA counts, temperatures),
not assumed.

### 📝 Documentation

Docs live in `docs/en/` and `docs/zh/` and must stay in sync — if you
change one language, please mirror the other (or note that a translation
is needed).

### 🔧 Code

#### Setup

```bash
git clone https://github.com/YOUR_USERNAME/auto-curve-shaper.git
cd auto-curve-shaper
# stdlib only — no pip install needed
```

#### Tests

```bash
python tests\test_derive.py      # solver, synthetic tables
python tests\test_pipeline.py    # full pipeline state machine (mocked hardware)
python -m py_compile *.py        # syntax check
```

`test_pipeline.py` never touches hardware — no probe calls, no reboots,
no real `state.json` (redirected to a temp file). **Known limitation:** the
mocks cannot catch workload-integration regressions. If you change
`frequency_monitor` or `workload` signatures, also run one short *real*
check: `measure_frequencies_load(20)` + `run_stability_test(10)` from an
elevated prompt.

#### Style

- PEP 8; `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants
- Docstrings on public functions; type annotations on public APIs
- Comments explain *why*, not *what*
- Measurement-infrastructure failures must raise (`MeasurementError`,
  `TemperatureError`, `WorkloadError`) — never be mistaken for an unstable
  configuration

#### Commits & PRs

```
type: short summary (<= 50 chars)

Why the change is needed, how it solves it, any side effects.

Fixes #123
```

Types: `feat` `fix` `docs` `style` `refactor` `test` `chore`.

PRs: tests pass, docs updated, describe what changed and how you tested it.
Hardware-behavior changes: state which CPU/board you verified on.

## Project structure

See the [architecture section](README.md#architecture) of the full
documentation. New modules should keep the separation the pipeline relies
on: `calibration.py` (hardware orchestration) is distinct from `derive.py`
(pure logic, offline-testable).

## Safety rules for PRs

- Never remove or weaken the stability gates, WHEA monitoring, or the caps
  without a strong, documented reason
- New load mechanisms must be terminated on failure paths (see
  `workload.LoadHandle` / `atexit` cleanup)
- Anything that stages CS writes must go through the reboot-state machine —
  runtime writes have no effect and create false test results

## Releasing

1. Bump `VERSION` / `RELEASE_DATE` in `config.py`
2. Update `CHANGELOG.md`
3. Run the offline test suite
4. Tag and publish

## Code of conduct

Be respectful, welcome newcomers, keep it technical. By participating you
agree to follow the project license terms.

---

Thanks for contributing! 🎉
