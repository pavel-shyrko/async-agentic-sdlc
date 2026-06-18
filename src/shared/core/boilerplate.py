# Engine-curated baseline files for the repository-preparation block of TASK-01.
#
# These canonical texts (the MIT license, the per-environment .gitignore) used to be REPRODUCED by the
# TPM agent verbatim inside the ticket — which reliably tripped Gemini's RECITATION filter (the license
# and github/gitignore templates match training data word-for-word). The engine now injects them
# deterministically at ticket materialisation, so the LLM never reproduces them and the block is
# byte-stable. The .gitignore is reused from environments.py (single source of truth).
from src.shared.core.environments import get_gitignore_template

# Fallback copyright holder when the run carries no better attribution (keeps the license valid rather
# than leaving a placeholder the Developer agent would have to guess at).
DEFAULT_LICENSE_HOLDER = "The Project Authors"

# Full literal MIT license with {year}/{holder} slots. Identical to the canonical OSI text.
MIT_LICENSE_TEMPLATE = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


def render_mit_license(holder: str = "", year: str = "2026") -> str:
    """Render the canonical MIT license text, defaulting an empty holder to DEFAULT_LICENSE_HOLDER."""
    return MIT_LICENSE_TEMPLATE.format(year=year, holder=(holder or "").strip() or DEFAULT_LICENSE_HOLDER)


def build_baseline_block(environment_id: str, holder: str = "", year: str = "2026") -> str:
    """Assemble the engine-provided baseline-files block appended to TASK-01's description.

    Contains the canonical ``.gitignore`` for ``environment_id`` (reused from environments.py) and the
    full MIT ``LICENSE`` — the two files the TPM no longer reproduces. The Developer agent reads the
    literal content here and applies each file idempotently (merge/refresh, never blind-overwrite).
    """
    gitignore = get_gitignore_template(environment_id).rstrip()
    license_text = render_mit_license(holder, year)
    return (
        "## Repository Baseline Files (engine-provided — apply VERBATIM)\n\n"
        "The following baseline files are engine-curated. Create each from the EXACT content below; do "
        "NOT improvise, reorder, or \"improve\" them. Apply idempotently — if a file already exists, "
        "reconcile it (merge missing entries / refresh stale content, preserve the rest) rather than "
        "blindly overwriting.\n\n"
        "### `.gitignore`\n"
        f"```gitignore\n{gitignore}\n```\n\n"
        "### `LICENSE`\n"
        f"```text\n{license_text}\n```\n"
    )
