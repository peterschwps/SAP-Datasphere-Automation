# Security Policy

## Supported Versions

Only the latest published release receives security updates.

| Version | Supported |
| --- | --- |
| [Latest release](https://github.com/peterschwps/SAP-Datasphere-CLI/releases/latest) | Yes |
| Earlier releases | No |

## Reporting a Vulnerability

Report suspected vulnerabilities privately through
[GitHub Private Vulnerability Reporting](https://github.com/peterschwps/SAP-Datasphere-CLI/security/advisories/new).
Do not open a public issue, discussion, or pull request.

Include:

- A concise description of the vulnerability and its potential impact.
- The affected release, operating system, and installation method.
- Sanitized reproduction steps or a minimal proof of concept using test data.
- The expected and observed behavior.
- A suggested remediation, if available.

Do not attach or paste:

- A real `settings.toml`, the `SECRET` environment-variable value, credentials,
  client secrets, authorization codes, tokens, browser cookies, session data,
  or data exported from the operating system credential store.
- Private tenant URLs, identifiers, object names, records, task files, results,
  or real request and response payloads.
- The unredacted [HTTP diagnostic log](README.md#http-logging), including its
  raw headers or bodies.
- Unsanitized logs, screenshots, fixtures, examples, or command output.

Use placeholders and synthetic test data. If sensitive material appears
necessary, describe its type without sending it and wait for guidance through
the private advisory.
