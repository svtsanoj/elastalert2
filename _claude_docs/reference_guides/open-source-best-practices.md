# Open source best practices

A practical guide for someone starting out. It covers contributing to an existing project (ElastAlert 2) and publishing your own project that builds on it (elastalert2-llm). Each section ends with what it means **for us**.

---

## 1. What "open source" actually commits you to

Open source means the code is published under a **licence** that lets others use, change and redistribute it. The licence is the legal contract. Everything else (issues, PRs, code of conduct) is community practice.

**Common licences**

| Licence | In one line | Obligations when you redistribute |
|---|---|---|
| **Apache-2.0** | Permissive, with an explicit patent grant | Keep the licence and copyright notices, keep any `NOTICE` file, and state significant changes |
| MIT / BSD | Permissive, very short | Keep the copyright and licence notice |
| GPL-3.0 | Copyleft | Derivative works must also be GPL, with source available |
| AGPL-3.0 | Copyleft that also covers network use | Even SaaS use must share the source |

ElastAlert 2 is **Apache-2.0** ([LICENSE](../../LICENSE)). That means:
- You can fork it, modify it, build on it commercially, and publish add-ons.
- You must keep the licence text and not remove copyright notices.
- Contributions you send upstream are accepted under the same licence (Apache-2.0 section 5: "inbound = outbound").

**For us:** publish elastalert2-llm under **Apache-2.0 too**. This matches upstream, is company-friendly, and has the patent grant. Add a `LICENSE` file and a short `NOTICE` file on day one.

> If you write the add-on on company time or with company data, check your employment contract or your company's open-source policy **before** publishing. Many companies need approval, and some want copyright assigned to them. Never publish real company log samples, index names, hostnames or ticket data. Use synthetic data only.

---

## 2. Fork, add-on or new project?

| Approach | When to use it | Downside |
|---|---|---|
| **Contribute upstream** (PR to jertel/elastalert2) | Bug fixes and small generic features everyone benefits from | You need maintainer review and follow their pace and style |
| **Add-on / plugin package** (depends on upstream) | Big or opinionated features that use the project's extension points | You maintain compatibility with upstream releases |
| **Hard fork** (diverge permanently) | Only when upstream is dead or refuses a direction you must have | Community split, and you maintain everything yourself |

A **GitHub fork** (like `svtsanoj/elastalert3`) is just your copy that stays linked to the original. It's how everyone sends PRs, and it isn't a hard fork unless you let it diverge.

**For us:**
- The **fork** is used only for upstream PRs. It will be renamed `elastalert2` so nobody mistakes it for a competing "v3".
- **elastalert2-llm** is an **add-on package** in its own repo. Users run `pip install elastalert2-llm` next to their existing ElastAlert 2, and nobody needs to clone our fork.
- Generic improvements found along the way (e.g. making `elastalert-test-rule --data` honour `filter`) go upstream as small, separate PRs.

---

## 3. Naming and branding

- Don't imply you are the official project. `elastalert2-llm` or `elastalert2-assistant` is fine, `elastalert3` or `official-elastalert` is not.
- Say what you depend on in the README: *"An add-on for ElastAlert 2. Not affiliated with the ElastAlert 2 maintainers."*
- **Check the name is free on PyPI** (`https://pypi.org/project/<name>/`) and on GitHub before you announce anything.
- Trademarks: "Elasticsearch", "Kibana" and "Elastic" are Elastic N.V. trademarks. Using them to describe compatibility ("works with Elasticsearch") is normal. Don't use their logos or put "Elastic" first in your project name.

---

## 4. The contribution loop (for any project)

1. **Read `CONTRIBUTING.md` first.** ElastAlert 2's is short and strict ([CONTRIBUTING.md](../../CONTRIBUTING.md)): tests are required, don't reformat existing code, update docs, schema, CHANGELOG, Helm chart and examples where relevant.
2. **Search issues and discussions** before starting. Someone may already be working on it, or the maintainers may have said no.
3. **For anything non-trivial, open an issue or discussion first** describing the problem and proposed approach. It saves you from writing code that gets rejected.
4. **One PR = one logical change.** Small PRs get reviewed; 2,000-line PRs sit for months.
5. **Match the existing style**, even where you would do it differently.
6. **Tests + docs + changelog entry** in the same PR.
7. **Make CI green before asking for review.** For ElastAlert 2 that is `make test-docker` ([Makefile](../../Makefile)), which runs pytest + flake8 in Docker.
8. **Be patient and kind in review.** Maintainers are volunteers. Reply to every comment, push fixes as new commits (don't force-push mid-review unless asked), and say thanks.

The exact git commands for this repo are in [upstream-contribution-workflow.md](upstream-contribution-workflow.md).

---

## 5. Commits and pull requests

**Commit messages**
- An imperative, short subject: `Add ServiceNow parent incident link`, not `added stuff` or `WIP`.
- A body only when the *why* isn't obvious.
- One logical change per commit where practical.

**PR descriptions** (ElastAlert 2 has a template at [.github/pull_request_template.md](../../.github/pull_request_template.md)):
- What changed and why, plus a link to the issue.
- How you tested it.
- The checklist items (tests, docs, schema, changelog).

**Branches:** never open a PR from your fork's `master`. Always use a topic branch, e.g. `fix/test-rule-filter`.

---

## 6. Versioning and changelogs

**Semantic versioning (`MAJOR.MINOR.PATCH`):**
- MAJOR: breaking changes (config keys removed or renamed, behaviour changes users must react to).
- MINOR: new features, backwards compatible.
- PATCH: bug and security fixes.

Before `1.0.0` you may break things in MINOR releases, but say so loudly in the changelog.

ElastAlert 2 uses `2.MINOR.PATCH` and never bumps the major (see [CONTRIBUTING.md](../../CONTRIBUTING.md) → Releases). Its [CHANGELOG.md](../../CHANGELOG.md) groups changes under **Breaking changes / New features / Other changes**, with a PR link and the author's handle on every line. Contributors add their line under the `2.TBD.TBD` section at the top.

**For us:** start elastalert2-llm at `0.1.0`, keep a CHANGELOG in the same style, and declare the supported ElastAlert 2 range in `pyproject.toml` (`elastalert2>=2.31,<3`).

---

## 7. Quality gates: tests, linting, CI

- **Tests are the entry ticket.** Every new code path needs a test that fails without your change.
- **Mock external systems** (Elasticsearch, Jira, HTTP, LLM servers) in unit tests. Keep a small, separately marked set of integration tests for real services. ElastAlert 2 marks those with `@pytest.mark.elasticsearch` and only runs them with `--runelasticsearch` ([tests/conftest.py](../../tests/conftest.py)).
- **Linting** keeps diffs about substance. ElastAlert 2 uses flake8 with a 140-column limit ([setup.cfg](../../setup.cfg)).
- **CI on every PR:** GitHub Actions runs the same commands you run locally. ElastAlert 2: [.github/workflows/master_build_test.yml](../../.github/workflows/master_build_test.yml).
- **Coverage** is a guide, not a goal. Aim for high coverage of the logic, not of trivial glue.

---

## 8. Documentation is part of the product

- The **README** answers: what is it, why use it, how to install, a 30-second example, links to the full docs, and the licence.
- **User docs** cover every config option with an example. ElastAlert 2 uses Sphinx (reStructuredText) in [docs/source](../../docs/source), published on ReadTheDocs via [.readthedocs.yaml](../../.readthedocs.yaml).
- **Contributor docs** (`CONTRIBUTING.md`) explain how to set up, test and submit.
- Keep docs next to code and change them in the same PR ("docs as code").

---

## 9. Community files (GitHub recognises these)

| File | Purpose | ElastAlert 2 has it? |
|---|---|---|
| `README.md` | Front page | Yes |
| `LICENSE` | Legal terms | Yes (Apache-2.0) |
| `CONTRIBUTING.md` | How to contribute | Yes |
| `SECURITY.md` | How to report vulnerabilities privately | Yes ([SECURITY.md](../../SECURITY.md)) |
| `CODE_OF_CONDUCT.md` | Behaviour expectations | No |
| `.github/ISSUE_TEMPLATE/*` | Structured bug reports | Yes (bug_report.md) |
| `.github/pull_request_template.md` | PR checklist | Yes |
| `CHANGELOG.md` | Release notes | Yes |

**For us:** ship all of these in elastalert2-llm from the first public commit. A Contributor Covenant `CODE_OF_CONDUCT.md` is the common default.

---

## 10. Security hygiene

- **Never commit secrets.** Use environment variables or `.env` files that are gitignored, and commit a `.env.example` with placeholders instead. Note that ElastAlert 2's root [.gitignore](../../.gitignore) already ignores `/config.yaml`, `/rules/` and `my_rules`.
- If you do leak a secret: **rotate it first**, then clean history. Deleting the commit is not enough, because forks and caches keep it.
- Respond to vulnerability reports privately (via `SECURITY.md`), fix them, then disclose.
- For an LLM tool that reads logs, document what data leaves the machine. With a local model the answer is "nothing", which is a selling point. With the optional Claude backend, log samples are sent to the API, so make that explicit in the UI.
- Code generated by an LLM must be reviewed before it runs. elastalert2-llm will require approval for every generated module.

---

## 11. Publishing a Python package

1. **Metadata in `pyproject.toml`**: name, version, description, licence, classifiers, `requires-python`, dependencies, extras, `project.urls`, and console scripts.
2. **Build**: `python -m build` produces an sdist and a wheel in `dist/`.
3. **Test the upload**: publish to **TestPyPI** first and install from there in a clean venv.
4. **Publish with Trusted Publishing** from GitHub Actions. PyPI trusts your repo's workflow through OIDC, so there's no API token to leak. ElastAlert 2 does exactly this: see [.github/workflows/python-publish.yml](../../.github/workflows/python-publish.yml), which uses `pypa/gh-action-pypi-publish` with `id-token: write` and runs only for `github.repository_owner == 'jertel'`.
5. **Tag releases** (`v0.1.0`), create a GitHub Release with the changelog section, and keep `main` releasable.

---

## 12. Maintaining a project once people use it

- **Triage issues** with labels (`bug`, `enhancement`, `question`, `good first issue`), and close duplicates politely with a link.
- **Deprecate before removing**: warn for at least one minor release and document the migration.
- **Track upstream**: when ElastAlert 2 releases, run your test suite against it, and pin or raise the supported range.
- **Keep the scope clear**: a short "non-goals" section in the README saves many arguments.
- **Say no kindly**, with a reason and an alternative ("this would fit better as a custom enhancement; here's how").

---

## 13. Building a community around elastalert2-llm

- Announce it where the users are. ElastAlert 2 has **GitHub Discussions** at `github.com/jertel/elastalert2/discussions`; a "Show and tell" post linking the add-on is appropriate. Don't open issues or PRs just to advertise.
- Lower the barrier: a one-command demo (the Docker dev stack plus a seeded scenario), a GIF in the README, and `good first issue` labels.
- Respond quickly to the first few issues and PRs. Early contributors decide whether a project feels alive.

---

## Checklists

**Before your first upstream PR**
- [ ] Read CONTRIBUTING.md and the PR template
- [ ] Opened or linked an issue or discussion (for non-trivial changes)
- [ ] Branch from `upstream/master`
- [ ] Tests added; `make test-docker` (or pytest + flake8) passes
- [ ] Docs, schema.yaml, CHANGELOG (and chart/examples if relevant) updated
- [ ] No unrelated formatting changes

**Before the first public release of elastalert2-llm**
- [ ] Employer approval (if applicable); no real company data anywhere in the repo or its history
- [ ] Name checked on PyPI and GitHub
- [ ] LICENSE, NOTICE, README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG
- [ ] CI green on all supported Pythons; TestPyPI install works in a clean venv
- [ ] Trusted Publishing configured; release tagged
