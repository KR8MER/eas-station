# Contributing to EAS Station

Thank you for your interest in improving EAS Station. We welcome issues, feature proposals, and code contributions that advance experimental emergency alert tooling while keeping the project safe for lab use.

## Code of Conduct

Be respectful and constructive. EAS Station is maintained by volunteers supporting the public-safety and amateur-radio communities. Provide helpful context, avoid personal attacks, and keep communication focused on building a reliable platform.

## Licensing and Copyright

- The EAS Station source code is released under the [MIT License](../../LICENSE). Timothy Kramer (KR8MER) retains the project copyright.
- By contributing, you agree that your submissions will be licensed under the MIT License and may be redistributed under those terms.

## Developer Certificate of Origin (DCO)

This project uses a Developer Certificate of Origin workflow instead of a Contributor License Agreement. The DCO keeps the process lightweight while ensuring that all contributors affirm they have the right to submit their work.

Each commit must contain a `Signed-off-by` line, which you can add automatically with `git commit -s`. The signature certifies that you wrote the code or have the rights to pass it on under the project license. The wording of the DCO can be found at [developercertificate.org](https://developercertificate.org/).

**Example commit message:**

```
Add new alert visualization panel

Improve the admin dashboard by adding a Highcharts visualization of alert volume.

Signed-off-by: Your Name <you@example.com>
```

If you contribute on behalf of an organization, ensure you have the necessary authorization to do so before signing off.

## How to Contribute

1. **Fork the repository** and create a topic branch (`feature/...`, `fix/...`, or `docs/...`).
2. **Follow the development guidelines** in [`AGENTS.md`](../development/AGENTS) and existing code patterns.
3. **Add tests or documentation** that cover your changes when possible.
4. **Update release metadata.** Append notes under the `[Unreleased]` heading in [`CHANGELOG.md`](../reference/CHANGELOG) and bump the root [`VERSION`](../../VERSION) file (plus `.env.example`) when behaviour changes. The guardrail test `tests/test_release_metadata.py` enforces this alignment.
5. **Run the test suite or targeted regression checks** (alert ingest, SAME generation, GPIO control, audio playout) before opening a pull request so reviewers know nothing critical regressed.
6. **Submit a pull request** describing the change, its motivation, and any verification steps performed.

We encourage proposals and discussion via GitHub issues before major changes. Thanks for helping build EAS Station!
