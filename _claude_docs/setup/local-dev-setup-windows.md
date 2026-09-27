# Local development setup (Windows 11)

Tested on this PC on 2026-09-27: Windows 11 Pro, Python 3.13.5, Git Bash, Docker Desktop 27.4 (WSL2 backend), Ollama 0.34.2.

The result: ElastAlert 2 installed in editable mode in a virtualenv, the test suite running, and linting working. Running against a real Elasticsearch is covered in [elasticsearch-kibana-local.md](elasticsearch-kibana-local.md).

---

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.13 or 3.14 | ElastAlert 2 supports 3.13/3.14 (3.12 is deprecated) | `python --version` |
| Git | Source control (Git Bash also gives you a Unix-like shell) | `git --version` |
| Docker Desktop (WSL2 backend) | Local Elasticsearch/Kibana, and the CI-equivalent test run | `docker --version`; `wsl -l -v` shows `docker-desktop` |
| VS Code + Python extension | Editing and debugging | — |
| `make` (optional) | The repo's Makefile targets. Not installed on Windows by default | `make --version` |

Without `make`, run the underlying commands shown below; they're only one or two lines each. If you want `make`, run `winget search make` and install a GNU Make package (e.g. `GnuWin32.Make`), or use `make` inside a WSL Ubuntu shell.

---

## 2. Get the code

```bash
cd ~/Projects
git clone https://github.com/svtsanoj/elastalert3.git   # becomes .../elastalert2.git after the rename
cd elastalert3
git remote add upstream https://github.com/jertel/elastalert2.git
git remote -v    # origin = your fork, upstream = the original
```

Line endings: the repo's [.editorconfig](../../.editorconfig) says LF, and your git has `core.autocrlf=true`, so files are checked out with CRLF and committed as LF. That's fine. Make sure VS Code respects `.editorconfig` (install the EditorConfig extension) so new files don't end up with CRLF.

---

## 3. Create a virtualenv and install

From the repo root, in Git Bash:

```bash
python -m venv .venv                     # .venv* is already in .gitignore
source .venv/Scripts/activate            # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt      # runtime deps + pytest, flake8, tox, sphinx, pylint
pip install -e .                         # editable install: code changes apply without reinstalling
```

Check it:

```bash
elastalert --help
elastalert-test-rule --help
elastalert-create-index --help
```

In VS Code, run **Python: Select Interpreter** and pick `.venv\Scripts\python.exe`.

---

## 4. Run the tests

CI runs pytest **from inside `tests/`** in a Linux container with `TZ=UTC`. Do the same:

```bash
cd tests
TZ=UTC0 python -m pytest . -n 4          # -n 4 = 4 parallel workers (pytest-xdist)
python -m flake8 --config ../setup.cfg . # lint, same as CI
cd ..
```

**Expected on native Windows: 1127 passed, 4 skipped, 4 failed.** The 4 failures are environment artefacts, not bugs you introduced:

| Test | Why it fails on Windows |
|---|---|
| `base_test.py::test_time_enhancement`, `util_test.py::test_pretty_ts` | They assume the machine's local timezone is UTC. Windows ignores most `TZ` values, so your IST (+05:30) leaks in |
| `loaders_test.py::test_load_yaml_recursive_import`, `test_load_yaml_multiple_imports` | They compare paths built with `/` against Windows `\` paths |

Running from the repo root instead of `tests/` adds two more failures (the `jinja` test module isn't importable from there), which is why `cd tests` matters.

> These four are a nice first upstream PR candidate: make the tests timezone-independent (patch `tzlocal`) and path-separator-independent (`os.path.join`/`pathlib`). Open an issue first.

### The CI-equivalent run (Docker, all green)

This is what `make test-docker` does, and the result is what counts for a PR. It needs Docker Desktop running:

```bash
docker compose -f tests/docker-compose.yml --project-name elastalert build tox
docker compose -f tests/docker-compose.yml --project-name elastalert run --rm tox tox -c tests/tox.ini
```

The first build takes several minutes. It mounts the repo into the container, so it tests your working copy.

### Useful pytest variations

```bash
cd tests
python -m pytest alerters/slack_test.py -q            # one file
python -m pytest -k "frequency" -q                    # tests whose name matches
python -m pytest . --cov=../elastalert --cov-report=term-missing   # coverage
python -m pytest . --runelasticsearch -m elasticsearch            # integration tests vs a real ES (see tests/conftest.py)
```

---

## 5. Build the docs locally

```bash
cd docs
python -m sphinx -b html -W source build/html    # -W: warnings are errors, as in CI
start build/html/index.html                      # open in the browser (Git Bash: `start`; PowerShell: `ii`)
```

Or `tox -c tests/tox.ini -e docs`. Edit `.rst` files under `docs/source/`.

---

## 6. Debugging in VS Code

`.vscode/launch.json` (VS Code creates `.vscode/` locally; don't commit it upstream):

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "elastalert (one rule, debug mode)",
      "type": "debugpy",
      "request": "launch",
      "module": "elastalert.elastalert",
      "args": ["--config", "config.yaml", "--verbose", "--debug", "--rule", "my_rules/example.yaml"],
      "cwd": "${workspaceFolder}"
    },
    {
      "name": "test-rule against mock data",
      "type": "debugpy",
      "request": "launch",
      "module": "elastalert.test_rule",
      "args": ["my_rules/example.yaml", "--config", "config.yaml", "--data", "my_rules/sample.json", "--formatted-output"],
      "cwd": "${workspaceFolder}"
    },
    {
      "name": "pytest current file",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-q", "-p", "no:xdist"],
      "cwd": "${workspaceFolder}/tests",
      "env": {"TZ": "UTC0"}
    }
  ]
}
```

Good breakpoints for learning the flow:
- `ElastAlerter.run_rule` ([elastalert.py:851](../../elastalert/elastalert.py#L851))
- `RulesLoader.load_options` ([loaders.py:314](../../elastalert/loaders.py#L314))
- `FrequencyRule.add_data` ([ruletypes.py:232](../../elastalert/ruletypes.py#L232))
- `ElastAlerter.send_alert` ([elastalert.py:1362](../../elastalert/elastalert.py#L1362))

---

## 7. Files you create locally (and never commit)

The root [.gitignore](../../.gitignore) already covers them:

| Path | Purpose |
|---|---|
| `config.yaml` (root) | Your global config pointing at the local ES (`/config.yaml` is ignored) |
| `my_rules/` | Your experimental rules (`my_rules` is ignored) |
| `.venv/` | Virtualenv |

---

## 8. Keeping it working

- After pulling upstream changes: `pip install -r requirements-dev.txt` again (the dependency pins change often).
- If `pip install -e .` fails on `cffi`/`pycryptodomex`: `pip install --upgrade pip setuptools wheel`, then retry.
- Next step: [elasticsearch-kibana-local.md](elasticsearch-kibana-local.md).
