# Checking a release

Release images are signed in the release workflow (`.github/workflows/release.yml`) with cosign, without a long-lived key. The signature records which workflow built the image, and from which tag. The images also have a signed SBOM (the list of packages in the image) and signed build provenance (a record of how and where the image was built).

The updater will run the same checks before it installs a release (story E01-007). To run them by hand, you need [cosign](https://docs.sigstore.dev/cosign/system_config/installation/) 3.0 or later and the [GitHub CLI](https://cli.github.com/). The image names with their digests are listed in the notes of each release on GitHub.

## Signature

```sh
cosign verify ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --certificate-identity-regexp '^https://github\.com/Franca-Language-Learning/Franca/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The check passes only for an image signed by the release workflow of this repository, running for a version tag.

## Build provenance and SBOM

```sh
gh attestation verify oci://ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --bundle-from-oci \
  --repo Franca-Language-Learning/Franca \
  --cert-identity-regex '^https://github\.com/Franca-Language-Learning/Franca/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$'

gh attestation verify oci://ghcr.io/franca-language-learning/franca-app@sha256:<digest> \
  --bundle-from-oci \
  --repo Franca-Language-Learning/Franca \
  --cert-identity-regex '^https://github\.com/Franca-Language-Learning/Franca/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
  --predicate-type https://spdx.dev/Document/v2.3
```

The identity check matters: a copy of the release workflow edited on another branch would also be called `release.yml`, but its certificate names that branch, not a version tag.

For the web server image, use `franca-caddy` in place of `franca-app`.

## Other checks in the release workflow

- Grype scans each image after it is pushed by digest. If there is a known vulnerability of high or critical severity that has a fix, the image is left unsigned and gets no version tag.
- Syft makes the SBOM, which is attached to the GitHub release as well.
- On every pull request, the *Container bundle* job runs the same scan on images built from the pull request.
