"""Write dist/version.json for the auto-update manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ytdpreviewer import __version__  # noqa: E402
from ytdpreviewer.release_config import BUNDLE_ASSET_NAME, GITHUB_REPO  # noqa: E402


def main() -> None:
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    bundle_url = ""
    if len(sys.argv) > 1:
        bundle_url = sys.argv[1].strip()
    notes = ""
    if GITHUB_REPO and not bundle_url:
        notes = (
            f"Publish tag v{__version__} on GitHub and attach {BUNDLE_ASSET_NAME} "
            f"to the release ({GITHUB_REPO})."
        )
    payload = {
        "version": __version__,
        "bundle_url": bundle_url,
        "notes": notes,
    }
    out = dist / "version.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
