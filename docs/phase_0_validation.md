# Phase 0 Validation and Handoff

## 1. Files created

```text
docs/
├── api_docs.md
├── architecture.md
├── data_sources.md
├── database_design.md
├── free_resource_verification.md
├── milestones.md
├── phase_0_plan.md
├── phase_0_validation.md
├── requirements.md
└── risk_register.md
```

This is intentionally smaller than the final application tree. Phase 1 creates source, test, infrastructure and tool configuration only after this baseline is accepted.

## 2. Exact PowerShell validation commands

Run from the workspace root:

```powershell
$required = @(
  'docs/phase_0_plan.md',
  'docs/requirements.md',
  'docs/architecture.md',
  'docs/database_design.md',
  'docs/api_docs.md',
  'docs/data_sources.md',
  'docs/free_resource_verification.md',
  'docs/risk_register.md',
  'docs/milestones.md',
  'docs/phase_0_validation.md'
)

$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Missing Phase 0 files: $($missing -join ', ')" }
"PASS: $($required.Count) Phase 0 files exist"
```

Expected output:

```text
PASS: 10 Phase 0 files exist
```

Check required content and risk gates:

```powershell
$checks = @(
  @{ File='docs/requirements.md'; Pattern='## 3. Required product surfaces' },
  @{ File='docs/architecture.md'; Pattern='```mermaid' },
  @{ File='docs/database_design.md'; Pattern='erDiagram' },
  @{ File='docs/api_docs.md'; Pattern='/api/v1' },
  @{ File='docs/data_sources.md'; Pattern='## 6. Stock-provider release gate' },
  @{ File='docs/free_resource_verification.md'; Pattern='2026-07-13' },
  @{ File='docs/risk_register.md'; Pattern='R-01' },
  @{ File='docs/milestones.md'; Pattern='| 20 |' }
)

foreach ($check in $checks) {
  if (-not (Select-String -LiteralPath $check.File -SimpleMatch $check.Pattern -Quiet)) {
    throw "Missing '$($check.Pattern)' in $($check.File)"
  }
}
'PASS: required Phase 0 sections and gates exist'
```

Expected output:

```text
PASS: required Phase 0 sections and gates exist
```

Check balanced Markdown code fences and encoding artifacts:

```powershell
Get-ChildItem -LiteralPath docs -Filter '*.md' | ForEach-Object {
  $content = Get-Content -LiteralPath $_.FullName -Raw
  $fenceCount = ([regex]::Matches($content, '(?m)^```')).Count
  if (($fenceCount % 2) -ne 0) { throw "Unbalanced code fence: $($_.Name)" }
}

$badChars = [string][char]0x00E2 + '|' + [string][char]0xFFFD
$mojibake = rg --line-number $badChars docs
if ($LASTEXITCODE -eq 0) { throw "Possible encoding damage:`n$mojibake" }
if ($LASTEXITCODE -gt 1) { throw 'rg failed while checking encoding' }
'PASS: code fences are balanced and no common mojibake markers were found'
```

Expected output:

```text
PASS: code fences are balanced and no common mojibake markers were found
```

List the final Phase 0 tree:

```powershell
Get-ChildItem -LiteralPath docs -File | Sort-Object Name | Select-Object -ExpandProperty Name
```

## 3. Optional visual review

Open `docs/architecture.md` and `docs/database_design.md` in VS Code Markdown Preview (`Ctrl+Shift+V`). Confirm that all Mermaid diagrams render, labels are readable and no relationship crosses a trust boundary incorrectly. Mermaid rendering depends on the preview extension/client; the Markdown source remains the canonical artifact.

## 4. Common errors

| Symptom | Cause | Resolution |
|---|---|---|
| `rg` is not recognized | Ripgrep is not on `PATH` | Construct `$badChars` as above, then use `Get-ChildItem docs -Filter '*.md' \| Select-String -Pattern $badChars` |
| Mermaid shows plain text | Markdown preview lacks Mermaid support | Use the built-in/current VS Code Markdown preview or a reviewed Mermaid extension; do not alter the diagram into an image-only source |
| Official link returns 403/429 | Provider blocks automated/head requests | Open it interactively, respect rate limits and record the check date; do not loop retries |
| Oracle console shows different limits | Account/region/status differs from public baseline | Treat account limits as authoritative, update the verification record and do not provision paid resources without approval |
| Stock quote source still says blocked | This is intentional, not missing work | Record explicit external-display permission and quota before changing the gate |
| PowerShell displays odd punctuation | Terminal encoding mismatch | Use PowerShell 7/UTF-8 and keep files encoded as UTF-8; the repository content should not be rewritten as ANSI |
| `fatal: not a git repository` | This empty workspace has not been initialized yet | Keep the commit message as a recommendation; initialize the repository as an explicit Phase 1 step before committing |

## 5. Completion checklist

- [x] Final functional and non-functional requirements are defined.
- [x] User roles and backend authorization boundaries are defined.
- [x] Modular-monolith, request, deployment and RAG diagrams are present.
- [x] Core database tables, added operational tables, constraints and indexes are planned.
- [x] Versioned API routes and access levels are cataloged.
- [x] SEC, Binance, CoinGecko and stock-source decisions are documented.
- [x] Current free hosting, CI/CD, registry, monitoring, DNS, email and backup allowances are checked against official sources.
- [x] Stock display licensing is recorded as a blocking production gate, not hidden.
- [x] Risk register has owners, mitigations and contingencies.
- [x] All 21 phases have measurable exit gates.
- [x] Windows PowerShell validation and expected output are documented.
- [x] Recommended Git commit is provided.
- [ ] Product owner accepts the Phase 0 baseline and authorizes Phase 1.

## 6. Recommended Git commit

```powershell
git add -- docs
git commit -m "docs: establish phase 0 production planning baseline"
```

The command is a recommendation only. The current workspace is not yet a Git repository; repository initialization belongs to Phase 1. After initialization, review `git diff --staged` before committing. Phase 1 should start only after the final unchecked item above is accepted.
