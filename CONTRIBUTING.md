# Contributing to project-oracle

Thank you for your interest in contributing! This document explains how to get
involved, from filing issues to landing code.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you agree to uphold it. Report concerns to the maintainers.

## Ways to Contribute

- **Bug reports** — open an issue using the bug report template
- **Feature requests** — open an issue using the feature request template
- **Documentation** — typos, clarifications, examples
- **Code** — fixes, features, tests; follow the workflow below

## Development Setup

    git clone https://github.com/mikelane/project-oracle
    cd project-oracle
    uv sync --all-groups

## Pull Request Workflow

1. **File an issue first** for non-trivial changes — avoids duplicate effort
2. Fork the repo and create a branch: `git checkout -b issue-NNN-short-description`
3. Write tests _before_ code (TDD)
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/)
5. Push and open a PR; fill in the template fully
6. Address review feedback; one approval required to merge

## Commit Style

    type(scope): short imperative summary

    - type: feat | fix | chore | docs | test | refactor | perf | ci
    - scope: optional, e.g. (parser), (cli), (api)
    - summary: lowercase, no trailing period, <= 72 chars

## Reporting Security Issues

**Do not open a public issue for security vulnerabilities.** See [SECURITY.md](SECURITY.md).

## Questions?

Open a [Discussion](https://github.com/mikelane/project-oracle/discussions) — issues are
for confirmed bugs and accepted feature requests.
