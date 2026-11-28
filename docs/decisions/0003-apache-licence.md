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

The product owner chose the Apache License 2.0, with a NOTICE file and the copyright line "Copyright 2026 the Franca authors". The attribution that the owner wants is in NOTICE. Under section 4(d) of the licence, copies of the code and works derived from it have to keep the attribution notices in NOTICE.

### Consequences

- The licence and the copyright line apply to the original work in this repository that was written for Franca, including the made-up test pack in `packs/fixture/` and not including the `speech/` folder. Material from other projects keeps its own copyright and licence. The course material is kept in a private repository and is not covered by the Apache License.
- A third-party file that is copied into the repository is listed in NOTICE with its source and its licence, including the copyright line. The licence text goes in `LICENSES/`, and the file's own header is not changed.
- The `speech/` folder was also written by the Franca authors and stays GPL-3.0-or-later.
- Packages with a licence on the deny list in `.github/workflows/ci.yml`, such as GPL and AGPL, are still refused outside `speech/`, because a program that includes them would have to be distributed under their terms.
