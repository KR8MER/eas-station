## Summary

<!-- What does this PR do, and why? 1-3 bullet points. -->

-

## Test plan

<!-- How did you verify this works? Check off what applies, add what's missing. -->

- [ ] Ran the relevant tests locally (`pytest tests/...`)
- [ ] Ran the full suite (`pytest tests/`) if the change touches shared code
- [ ] Tested manually in the browser, if this touches the UI
- [ ] Verified on bare metal / a real device, if this touches hardware (GPIO, SDR, displays)

## Checklist

- [ ] `VERSION` bumped and `docs/reference/CHANGELOG.md` updated under a new heading (see `docs/development/AGENTS.md` §9)
- [ ] No secrets or credentials committed
- [ ] Touched files stay within the ~400-line module / ~300-line template guidance, or were split
- [ ] Docs updated if user-facing behavior changed (`templates/help.html`, `templates/about.html`, relevant `docs/`)
