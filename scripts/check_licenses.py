"""Fail the build when an installed distribution uses a licence outside the allow-list.

Direct dependencies are documented in ``THIRD_PARTY_LICENSES.md``. This script
checks the whole environment, including transitive packages, because that is
what actually ships. ``psycopg`` and ``certifi`` are named exceptions.
"""

from __future__ import annotations

import sys
from importlib import metadata

ALLOWED = {
    "mit",
    "apache-2.0",
    "apache2",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "psf-2.0",
    "isc",
    "0bsd",
    "unlicense",
    "hpnd",
    "zlib",
    "mit or apache-2.0",
    "apache-2.0 or bsd-3-clause",
}

# Package name -> licence we accept only because THIRD_PARTY_LICENSES.md says so.
EXCEPTIONS = {
    "psycopg": "lgpl-3.0-only",
    "psycopg-binary": "lgpl-3.0-only",
    "psycopg2": "lgpl-3.0-only",
    "psycopg2-binary": "lgpl-3.0-only",
    "certifi": "mpl-2.0",
}

_ALIASES = {
    "mit license": "mit",
    "mit": "mit",
    "bsd license": "bsd",
    "bsd": "bsd",
    "3-clause bsd license": "bsd-3-clause",
    "bsd-3-clause": "bsd-3-clause",
    "bsd 3-clause": "bsd-3-clause",
    "apache software license": "apache-2.0",
    "apache-2.0": "apache-2.0",
    "apache 2.0": "apache-2.0",
    "apache license 2.0": "apache-2.0",
    "lgpl-3.0-only": "lgpl-3.0-only",
    "gnu lesser general public license v3 (lgplv3)": "lgpl-3.0-only",
    "gnu library or lesser general public license (lgpl)": "lgpl-3.0-only",
    "mpl-2.0": "mpl-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "python software foundation license": "psf-2.0",
    "historical permission notice and disclaimer (hpnd)": "hpnd",
    "isc license": "isc",
    "isc license (iscl)": "isc",
}


def normalize(value: str) -> str:
    text = " ".join(value.replace("\n", " ").split()).strip().lower()
    return _ALIASES.get(text, text)


def license_of(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression
    declared = dist.metadata.get("License") or ""
    if declared and len(declared) < 120:
        return declared
    classifiers = dist.metadata.get_all("Classifier") or []
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return ""


def allowed(name: str, raw: str) -> bool:
    parts = [normalize(part) for part in raw.replace(" OR ", " or ").split(" or ")]
    if any(part in ALLOWED for part in parts):
        return True
    expected = EXCEPTIONS.get(name.lower())
    return expected is not None and any(part == expected or expected in part for part in parts)


def main() -> int:
    failures: list[str] = []
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        raw = license_of(dist)
        if not raw:
            failures.append(f"{name}: no licence metadata")
            continue
        if not allowed(name, raw):
            failures.append(f"{name}: {raw}")
    if failures:
        print("Licence check failed:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(f"Licence check passed for {len(list(metadata.distributions()))} distributions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
