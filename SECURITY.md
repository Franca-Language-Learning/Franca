# Security policy

## About Franca

Franca is a language-learning app that is used by two learners. It runs on one PC and is reached from their devices over a private network. The code is public in this repository so that it can be read and checked. The course material and the learners' data are private, and they are not in this repository.

## Supported versions

Security fixes are made to the latest release. Older releases are not patched. A fix is published as a new release, and it is installed on the owner's PC by Franca's updater the next night.

## Reporting a vulnerability

Please report a vulnerability privately through GitHub, and not in a public issue or pull request.

1. Open the [form for a private report](https://github.com/Franca-Language-Learning/Franca/security/advisories/new). It is also reached with the "Report a vulnerability" button on the Security tab of the repository.
2. Fill in the form and submit it.

The report can be read by you and the owner of the repository. It is not public. You need a GitHub account to use the form, and there is no other way to report at the moment.

Please test on a copy of Franca that you run yourself. The owner's installation has real learners' data and is not open to testing.

## What to put in a report

- The release or commit that you looked at
- What the problem is, and what someone could do with it
- The steps to reproduce it, or a small proof of concept
- Whether you have told anyone else about it

If you are not sure that something is a vulnerability, report it anyway.

## What happens after a report

The owner reads the report and replies within 14 days, to say whether the problem is confirmed and what is planned. If it is confirmed, the fix is prepared in private and published in a new release. After the release, a security advisory is published on GitHub. You are named in the advisory if you want to be.

## Disclosure

Please give the owner time to release a fix before you talk about the problem in public. The aim is a fix within 90 days of the report. If that is not possible, the owner tells you why and agrees a new date with you.

A vulnerability in a package that Franca uses belongs with that package's project. If Franca is affected in a way that the package's own fix does not cover, please report that here as well.
