# Upstream contribution workflow (fork → jertel/elastalert2)

The exact git steps for sending a change from your fork to the upstream ElastAlert 2 project. The general "why" is in [open-source-best-practices.md](open-source-best-practices.md).

**Terms**
- `upstream` = `github.com/jertel/elastalert2`, the real project.
- `origin` = your fork: `github.com/svtsanoj/elastalert3`, soon renamed `elastalert2`.
- A **PR** goes from a branch on `origin` into `upstream/master`.

---

## 1. One-time setup

### 1a. Rename the fork (GitHub UI)

Your fork is a real, linked GitHub fork of jertel/elastalert2 (verified via the GitHub API: `"fork": true`, parent `jertel/elastalert2`). Only the name needs to change:

1. Go to `https://github.com/svtsanoj/elastalert3` → **Settings** → **General** → *Repository name* → `elastalert2` → **Rename**.
2. GitHub keeps the fork link and redirects the old URL, but update your local clone anyway:

```bash
git remote set-url origin https://github.com/svtsanoj/elastalert2.git
git remote add upstream https://github.com/jertel/elastalert2.git   # skip if you already added it
git remote -v
```

3. Optional: rename the local folder `elastalert3` → `elastalert2`, then reopen it in VS Code. Recreate `.venv` afterwards, because venvs hard-code their path.

### 1b. Your identity

```bash
git config --global user.name  "svtsanoj"
git config --global user.email "<your email or GitHub no-reply address>"
```

This address is public in every commit. To hide it, use GitHub's no-reply address (Settings → Emails → "Keep my email address private"), which looks like `<id>+svtsanoj@users.noreply.github.com`.

---

## 2. Branch model

| Branch | Lives on | Purpose |
|---|---|---|
| `master` (fork) | origin | Your working base. It currently also carries `_claude_docs/`. **Never open a PR from it** |
| `upstream/master` | upstream | The source of truth. Every PR branch starts here |
| `fix/<topic>`, `feat/<topic>`, `docs/<topic>` | origin | One branch per PR, created from `upstream/master` |

Starting PR branches from `upstream/master` (not your `master`) guarantees that `_claude_docs/`, `addons/` or anything else personal never ends up in an upstream PR.

---

## 3. Making a contribution

```bash
# 0. Discuss first (for anything non-trivial): open an issue or discussion on jertel/elastalert2

# 1. Get the latest upstream
git fetch upstream

# 2. New branch from upstream/master
git switch -c fix/test-rule-filter upstream/master

# 3. Make the change + tests + docs + CHANGELOG line
#    (see the checklists in elastalert2-repo-guide.md §7)

# 4. Test like CI does
cd tests && TZ=UTC0 python -m pytest . -n 4 && python -m flake8 --config ../setup.cfg . && cd ..
#    ...and ideally the Docker run (all green on Linux):
docker compose -f tests/docker-compose.yml --project-name elastalert run --rm tox tox -c tests/tox.ini

# 5. Commit (small, clear messages)
git add -p                       # review hunks as you stage them
git commit -m "Apply rule filter when running test-rule with --data"

# 6. Push the branch to your fork
git push -u origin fix/test-rule-filter
```

Then on GitHub, choose **Compare & pull request**:
- base repository `jertel/elastalert2`, base `master`
- head repository `svtsanoj/elastalert2`, compare `fix/test-rule-filter`

Fill in the [PR template](../../.github/pull_request_template.md).

### CHANGELOG line

Add it under the top `# 2.TBD.TBD` section in [CHANGELOG.md](../../CHANGELOG.md). You only know the PR number after opening the PR, so open it, then push a follow-up commit with the number:

```markdown
## Other changes
- [Tests] Apply rule filters when running elastalert-test-rule with --data - [#1780](https://github.com/jertel/elastalert2/pull/1780) - @svtsanoj
```

---

## 4. During review

- CI (`master_build_test`) runs `make test-docker` on your PR. Fix any red run before asking for review.
- Address comments with **new commits** (`git commit -m "Address review: ..."` + `git push`). Don't force-push unless a maintainer asks you to squash or rebase.
- If `upstream/master` moves on and you get conflicts:

```bash
git fetch upstream
git rebase upstream/master       # resolve conflicts, then: git rebase --continue
git push --force-with-lease      # needed after a rebase; --force-with-lease refuses to clobber unexpected remote changes
```

- Be patient. It's a volunteer-run project, and a friendly nudge after a week or two is fine.

---

## 5. After the merge

```bash
git switch master
git fetch upstream
git merge upstream/master        # bring your fork's master up to date (keeps your _claude_docs commits)
git push origin master
git branch -d fix/test-rule-filter
git push origin --delete fix/test-rule-filter
```

GitHub's **Sync fork** button on your fork's page does the same merge for `master`.

Your change reaches users in the next ElastAlert 2 release (see [elastalert2-repo-guide.md §9](elastalert2-repo-guide.md#9-releases-maintainers-only)).

---

## 6. Contribution ideas found so far

All are small and self-contained. Open an issue first:

1. `elastalert-test-rule --data` ignores `filter` ([test_rule.py:303](../../elastalert/test_rule.py#L303)); confirmed with the `simple-frequency` scenario.
2. `elastalert --rule <name>` loads every rule unless `scan_subdirectories` is on or a full path is given ([loaders.py:599-627](../../elastalert/loaders.py#L599)).
3. Four tests fail on native Windows (timezone and path-separator assumptions).
4. ServiceNow alerter: optional `parent_incident` / update support.

---

## 7. The add-on is a different repo

elastalert2-llm will live in its own repository (`svtsanoj/elastalert2-llm`), not in this fork. Its day-to-day workflow is simpler: you are the maintainer, so you work on feature branches, open PRs against your own `main`, and let CI gate them. See [design/agentic-alert-assistant.md](../design/agentic-alert-assistant.md).
