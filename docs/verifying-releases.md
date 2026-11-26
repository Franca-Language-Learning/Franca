# Checking a release

Each release image is signed in the release workflow (`.github/workflows/release.yml`) with cosign, without a long-lived key. The signature records which workflow and which tag built the image. The images also have a signed SBOM (the list of packages in the image) and signed build provenance.

The updater runs the same checks before it installs a release (story E01-007). To run them by hand, you need [cosign](https://docs.sigstore.dev/cosign/system_config/installation/) and the [GitHub CLI](https://cli.github.com/). The image names with their digests are listed in the notes of each release on GitHub.

## Signature

```sh
cosign verify ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --certificate-identity-regexp '^https://github\.com/Franca-Language-Learning/Franca/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The check passes only for an image signed by the release workflow of this repository, for a version tag.

## Build provenance and SBOM

```sh
gh attestation verify oci://ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --repo Franca-Language-Learning/Franca \
  --signer-workflow Franca-Language-Learning/Franca/.github/workflows/release.yml

gh attestation verify oci://ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --repo Franca-Language-Learning/Franca \
  --predicate-type https://spdx.dev/Document/v2.3
```

For the web server image, use `franca-caddy` in place of `franca-app`.

## What else is checked in the release workflow

- The image is scanned with Grype, and it is not signed if there is a known vulnerability of high or critical severity that has a fix.
- The SBOM is made with Syft and is attached to the GitHub release as well.
- The same scan runs on every pull request, in the *Container bundle* job.
