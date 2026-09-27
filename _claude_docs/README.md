# Project notes and guides

This folder holds the learning notes, setup guides, plans and design docs for:

1. Contributing to [ElastAlert 2](https://github.com/jertel/elastalert2), from this fork.
2. Building **elastalert2-llm**, a separate add-on package: an agentic LLM assistant that helps people create, debug and explain ElastAlert 2 alerts without knowing the rule syntax.

Every doc generated for this project lives here.

## Reading order

If you are new to the project, read in this order:

| # | Doc | What you get from it |
|---|-----|----------------------|
| 1 | [reference_guides/open-source-best-practices.md](reference_guides/open-source-best-practices.md) | How open source works in general: licences, forks, PRs, releases, community |
| 2 | [reference_guides/elastalert2-repo-guide.md](reference_guides/elastalert2-repo-guide.md) | A walkthrough of this codebase: layout, the run loop, design patterns, how to extend it, conventions |
| 3 | [setup/local-dev-setup-windows.md](setup/local-dev-setup-windows.md) | Get the code running and the tests passing on your Windows PC |
| 4 | [setup/elasticsearch-kibana-local.md](setup/elasticsearch-kibana-local.md) | Run Elasticsearch + Kibana 9.5.3 locally and point ElastAlert 2 at it |
| 5 | [setup/mock-data-and-scenarios.md](setup/mock-data-and-scenarios.md) | Create indices, seed realistic (messy) data and build test scenarios |
| 6 | [reference_guides/upstream-contribution-workflow.md](reference_guides/upstream-contribution-workflow.md) | The exact git workflow for sending a PR to jertel/elastalert2 |
| 7 | [design/agentic-alert-assistant.md](design/agentic-alert-assistant.md) | What elastalert2-llm is, and how it will work |
| 8 | [reference_guides/local-llm-models.md](reference_guides/local-llm-models.md) | Which local models to run on this PC, and how |

## Folder layout

```
_claude_docs/
  README.md             this index
  plans/                dated implementation plans
  reference_guides/     learning material you come back to
  setup/                step-by-step environment guides
  design/               design docs for things we build
```

## Current status (2026-09-27)

- [x] Plan agreed: [plans/2026-09-27-elastalert2-llm-plan.md](plans/2026-09-27-elastalert2-llm-plan.md)
- [x] Learning and setup docs written (this commit)
- [ ] Rename this GitHub fork from `elastalert3` to `elastalert2`. You do this in the GitHub UI; see [upstream-contribution-workflow.md](reference_guides/upstream-contribution-workflow.md#1-one-time-setup).
- [ ] Create the separate `elastalert2-llm` repo and start Phase 1 (skeleton, dev stack, seeder)
