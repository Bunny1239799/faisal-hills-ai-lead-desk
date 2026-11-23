# Security policy

## Supported versions

| Version | Supported |
|---|---|
| v1.0.0 (tag `v1.0.0`, branch `main`) | yes |
| anything older | no |

## What this project promises

The desk is designed so that a customer can never be shown a figure the
approved master does not support, and so that nothing is ever sent to a
dealer automatically. A report that breaks either promise is treated as a
security issue, not a feature request:

- a serving surface that can return an untraceable price, count or date;
- any path that sends, forwards or schedules a message without a human;
- a surface that exposes dealer names, phone numbers, plot numbers or raw
  chat text;
- a way for a test run or a tool to write into the live operator stores.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

1. Prefer GitHub's private reporting: **Security** tab, then
   **Report a vulnerability**.
2. Or email the maintainer at m.hanzala3940@gmail.com with the word
   `security` in the subject.

Include the affected file or route, what you observed, and what you expected.
You can expect an acknowledgement within a few days and a fix or a written
assessment for confirmed reports on the supported version.
