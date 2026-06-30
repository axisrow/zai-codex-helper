#!/usr/bin/env bash
# Phase 15 — pre-commit secret-scan hook (SECR-03, D-96, SC-2 defense layer 2).
#
# A grep-based defense-in-depth gate that runs BEFORE a commit lands. It greps
# the STAGED files for secret-like patterns and exits 1 if any match — catching
# an accidental `sk-...` literal or a hardcoded `ZAI_API_KEY="..."` assignment
# even when .gitignore was bypassed (e.g. `git add -f`). No external tool
# dependency (no gitleaks/detect-secrets) per D-96 — bash + grep only.
#
# Patterns (NARROW by design — T-15-05 accept):
#   1. `sk-[A-Za-z0-9]{20,}`  — a real ZAI/OpenAI API key shape.
#   2. `ZAI_API_KEY=[\"\']...[\"\']` — a literal assignment with a quoted value.
# The patterns deliberately do NOT match `environ.get("ZAI_API_KEY")` (the legit
# env read has no `=`; the name is inside quotes, not assigned). A docstring
# that merely mentions the name is also not matched.
#
# Wired into pre-commit via .pre-commit-config.yaml (local repo hook). Can also
# be run standalone: `bash scripts/pre-commit-secret-scan.sh`.
#
# Exit codes: 0 = clean (no secret-like literals staged); 1 = a staged file
# matched a pattern (commit aborted).

set -u

# Collect staged files (added/copied/modified — not deleted). Filter to text
# files only so a binary blob does not choke grep. `git diff --cached` reads
# the index, so this works whether or not the working tree differs.
mapfile -t staged < <(
  git diff --cached --name-only --diff-filter=ACMR 2>/dev/null \
    | grep -E '\.(py|ya?ml|toml|sh|json|txt|md|cfg|ini|conf)$' || true
)

if [ "${#staged[@]}" -eq 0 ]; then
  # No text files staged — nothing to scan.
  exit 0
fi

# The combined secret-like pattern. grep -E (extended regex). The two
# alternatives are alternated with `|`.
pattern='sk-[A-Za-z0-9]{20,}|ZAI_API_KEY[[:space:]]*=[[:space:]]*["'"'"'][^"'"'"']+["'"'"']'

found_hit=0
for f in "${staged[@]}"; do
  # Skip files that do not exist (deleted-then-added edge cases). grep -H
  # prefixes the filename; -n gives the line number; -E enables ERE.
  if [ ! -f "$f" ]; then
    continue
  fi
  if matches=$(grep -HnE "$pattern" "$f" 2>/dev/null); then
    echo "ERROR: secret-like literal found in staged file:" >&2
    echo "$matches" >&2
    echo "" >&2
    echo "If this is a REAL secret, do NOT commit it. If it is a false" >&2
    echo "positive (e.g. a test canary clearly named FAKE), document why." >&2
    found_hit=1
  fi
done

if [ "$found_hit" -ne 0 ]; then
  exit 1
fi

exit 0
