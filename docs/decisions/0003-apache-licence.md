---
status: accepted
date: 2026-11-27
decision-makers: product owner
---

# Apache License 2.0 for the public code

## Context and problem statement

In decision record 0001, the code was left without a licence until the product owner chose one. Without a licence, others can read the code but cannot reuse it, and the OpenSSF Scorecard has a "License" alert for the repository.

Which licence should the public code have?

## Decision outcome

The product owner chose the Apache License 2.0, with a NOTICE file and the copyright line "Copyright 2026 the Franca authors". The attribution that the owner wants is in NOTICE. Under section 4(d) of the licence, NOTICE has to be kept in copies of the code and in work based on it.

### Consequences

- The licence and the copyright line apply to the original work in this repository that was written for Franca, including the made-up test pack in `packs/fixture/`. Work that was not written for Franca keeps its own copyright and licence. The course material is not in this repository and is not licensed by it.
- A third-party file that is copied into the repository is listed in NOTICE with its source, its copyright holder and its licence. Its licence text goes in `LICENSES/`, and its own header is not changed.
- The speech container in `speech/` stays GPL-3.0-or-later.
- GPL and AGPL packages are still refused outside `speech/`, because their terms would apply to the app's code.
