"""CI/local check: catches `.env.example`/`.env.production.example` drifting
away from `voice_transcriber/config.py`'s actual fail-fast requirements.

config.py raises RuntimeError at import time for a handful of missing/wrong
env vars - some unconditionally (required in every mode), some only when
`PRODUCTION` is true (required in production only). Nothing enforces that
the two example templates actually mention those vars; add a new required
var to config.py, forget to add it to a template, and an operator following
that template hits a boot-time crash with no warning before that point.

How this derives "required" without hardcoding a second copy of the guard
list (which would itself drift): config.py follows one consistent
convention everywhere - every var is read as `NAME = os.environ.get(
'NAME', ...)`, i.e. the Python identifier and the env var string are
always identical. So:

  1. Regex every `VAR = os.environ.get('VAR', ...)` assignment to build a
     var-name -> env-key map (they're the same string here, but this keeps
     the script correct if that convention every changes for one var).
  2. Regex every `if <condition>:\n    raise RuntimeError` block, and pull
     out which known var names appear in <condition>.
  3. A condition that does NOT mention `PRODUCTION` is required in every
     mode (e.g. `if not DATABASE_URL`) - required in dev AND prod.
     A condition that DOES mention `PRODUCTION` is required in production
     only (e.g. `if PRODUCTION and not os.environ.get('SONIOX_API_KEY')`).

This means a newly added guard is picked up automatically the next time
this script runs - nobody has to remember to update this file too.

Advisory-but-failing: prints exactly which key is missing from which
template, then exits 1. Never auto-fixes the templates - which value a
newly-required var should get in the production template is an operator
decision, not something to guess silently.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PY = REPO_ROOT / "voice_transcriber" / "config.py"
DEV_TEMPLATE = REPO_ROOT / ".env.example"
PROD_TEMPLATE = REPO_ROOT / ".env.production.example"

_ASSIGNMENT_RE = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*=\s*os\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]",
    re.MULTILINE,
)
# Non-greedy block match: an `if ...:` line followed by an indented body
# whose first statement raises RuntimeError - matches this file's exact
# guard shape (single-statement raise, no intervening logic).
_GUARD_RE = re.compile(
    r"^if\s+(.+?):\n(?:[ \t]+.*\n)*?[ \t]+raise RuntimeError",
    re.MULTILINE,
)
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9_]*\b")


def find_required_keys(config_src: str) -> tuple[set[str], set[str]]:
    """Returns (required_always, required_in_production) env-var-key sets."""
    var_to_key = dict(_ASSIGNMENT_RE.findall(config_src))
    known_vars = set(var_to_key)

    required_always: set[str] = set()
    required_in_prod: set[str] = set()

    for match in _GUARD_RE.finditer(config_src):
        condition = match.group(1)
        mentions_production = "PRODUCTION" in _IDENTIFIER_RE.findall(condition)
        referenced_vars = set(_IDENTIFIER_RE.findall(condition)) & known_vars
        for var in referenced_vars:
            key = var_to_key[var]
            if mentions_production:
                required_in_prod.add(key)
            else:
                required_always.add(key)

    # Unconditionally required implies required in production too.
    required_in_prod |= required_always
    return required_always, required_in_prod


def uncommented_keys(template_src: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", template_src, re.MULTILINE))


def main() -> int:
    config_src = CONFIG_PY.read_text(encoding="utf-8")
    required_always, required_in_prod = find_required_keys(config_src)

    dev_keys = uncommented_keys(DEV_TEMPLATE.read_text(encoding="utf-8"))
    prod_keys = uncommented_keys(PROD_TEMPLATE.read_text(encoding="utf-8"))

    missing_from_dev = sorted(required_always - dev_keys)
    missing_from_prod = sorted(required_in_prod - prod_keys)

    if not missing_from_dev and not missing_from_prod:
        print(
            f"OK - {len(required_in_prod)} production-required, "
            f"{len(required_always)} always-required env var(s) all present "
            f"in their template(s)."
        )
        return 0

    for key in missing_from_dev:
        print(
            f"::error::{key} is required in every mode (config.py raises "
            f"unconditionally without it) but is missing/commented-out in "
            f"{DEV_TEMPLATE.relative_to(REPO_ROOT)}"
        )
    for key in missing_from_prod:
        print(
            f"::error::{key} is required in production (config.py raises "
            f"when PRODUCTION and it's missing/wrong) but is missing/"
            f"commented-out in {PROD_TEMPLATE.relative_to(REPO_ROOT)}"
        )
    print(
        "\nDo not silently add these to the templates - decide what value "
        "(if any) an operator should be told to set, then update the "
        "template deliberately.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
