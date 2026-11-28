---
status: accepted
date: 2026-11-26
decision-makers: product owner
---

# Public code repository, private content repository

## Context and problem statement

Franca's build is split into five lanes that merge often, and every change runs layout tests at many widths in three browsers. On GitHub's free plan, a private repository owned by a person has no rulesets, so a merge can go ahead after a check has failed. A merge queue is available for a repository owned by an organisation, and for a private one only on GitHub Enterprise Cloud. Private repositories also have a monthly limit on pipeline minutes.

Where should Franca's code and content be kept?

## Considered options

- A: the code in a public repository owned by a free GitHub organisation, and the content in a private repository
- B: one private repository, with GitHub Pro (4 dollars a month)
- C: one private repository on GitHub Free

## Decision outcome

The product owner chose option A. It is the only option without a paid plan in which a failed check blocks a merge, a merge queue is available, and the pipeline has no minute limit.

### Consequences

- Anyone can read the app's code. The code holds no secrets and no course content.
- Course material pushed by mistake could not be fully withdrawn, so the content guard (story E01-014) runs before each commit, before each push and in the pipeline. See [repository-split.md](../repository-split.md).
- Franca can use the free tier of Harden-Runner and build attestations, because on the free plans they are available for public repositories.
- The code has no licence until the product owner chooses one, so others can read it and fork it on GitHub, but not reuse it. The speech container has to be GPL-3.0-or-later and has that licence now. On 27 November 2026 the product owner chose the Apache License 2.0 (decision record 0003).
