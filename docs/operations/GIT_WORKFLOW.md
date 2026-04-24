# Git Workflow

## Remote policy

- Repository is private on GitHub.
- Default branch: `main`.
- Local and remote must stay aligned after every phase.

## Phase commit checklist

```bash
git status --short --branch
python3 -m pytest -q
git add <phase files>
git commit -m "<Lore commit message>"
git push origin main
git status --short --branch
```

## Lore commit message template

```text
<why this phase exists>

<short narrative: constraints, approach, and tradeoffs>

Constraint: <external constraint>
Rejected: <alternative> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <future modifier warning>
Tested: <verification performed>
Not-tested: <known gaps>
```
