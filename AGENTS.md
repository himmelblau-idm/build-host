# AGENTS.md

Guidance for coding and ops agents working in this repository.

## Repository Context

This repo drives automated Himmelblau package builds and publishes distribution repositories.

## Build Failure Investigation

When investigating build failures, always check the published build logs first:

- Logs URL: https://packages.himmelblau-idm.org/logs/

Then verify published outputs for the relevant release/build:

- Stable results: https://packages.himmelblau-idm.org/stable/
- Nightly results: https://packages.himmelblau-idm.org/nightly/

Treat any of the following as strong indicators of a build failure:

- A missing `deb/` directory inside a release folder
- A missing `rpm/` directory inside a release folder
- Missing expected distribution builds within a release

## Expected Agent Behavior

- Use logs and published output structure as primary evidence before changing build logic.
- In incident notes or PRs, include the exact log path and which release/distribution output is missing.
