#!/usr/bin/env python
"""Django entrypoint. Settings module defaults to local development."""

from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docintel.config.settings.local")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
