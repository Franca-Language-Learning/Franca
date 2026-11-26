"""In the pipeline, the browser tests are run against Chromium from Playwright's image (story E01-004).

The image and @playwright/test have to be the same version, because the protocol between them changes with the version.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_browser_image_matches_the_playwright_package() -> None:
    package = json.loads((ROOT / "client" / "package.json").read_text(encoding="utf-8"))
    version = package["devDependencies"]["@playwright/test"]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f'"mcr.microsoft.com/playwright:v{version}-noble' in workflow
