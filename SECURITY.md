# Security policy

## About Franca

Franca is a language-learning app for two learners. It runs on one PC and is reached from their devices over a private network. One person looks after the project, and that person is called the owner in this file. The code is public in this repository so that it can be read and checked. The course material is in a private repository, and the learners' data is on the owner's PC. Neither is in this repository.

## Supported versions

Security fixes are made on the main branch and published as a new release. Older releases are not patched. A new release is installed on the owner's PC by Franca's updater during the next night.

## Reporting a vulnerability

Please report a vulnerability privately through GitHub, and not in a public issue or pull request.

1. Open the [form for a private report](https://github.com/Franca-Language-Learning/Franca/security/advisories/new). You can also open it from the Security tab of the repository, with the **Report a vulnerability** button.
2. Fill in the form and submit it.

The report can be read by you and the owner. It is not public. You need a GitHub account to use the form. There is no other way to report at the moment.

Please test on a copy of Franca that you run yourself. The owner's installation has the learners' real data and is not open to testing.

## What is in scope

These are in scope:

- The code and workflows in this repository, and the signed releases that are built from them
- Private material that was pushed to this repository by mistake, such as course material or a secret

These are out of scope:

- The owner's installation and private network
- The private repository with the course material, which outsiders cannot see
- A vulnerability in a package that Franca uses, or in a service such as GitHub or Tailscale. Please report it to that project. If Franca is affected in a way that the project's own fix does not cover, please report that here as well.

## What to put in a report

- The release or commit that you looked at
- What the problem is, and what someone could do with it
- The steps to reproduce it, or a small proof of concept
- Whether you have told anyone else about it

If you are not sure that something is a vulnerability, report it anyway.

## What happens after a report

The owner replies within 14 days. In the reply, the owner tells you whether the problem is confirmed, or when that will be known. If there is no reply after 14 days, please add a comment to the report as a reminder.

If the problem is confirmed, the fix is prepared in private and published in a new release. After the release, a security advisory is published on GitHub, and you are named in it if you want to be. If the problem is not confirmed, the owner tells you why.

## Disclosure

Please give the owner time to release a fix before you talk about the problem in public. The aim is a fix within 90 days of the report. If that is not possible, the owner tells you why and agrees a new date with you.
