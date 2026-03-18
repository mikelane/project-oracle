"""Behave environment setup — creates temp directories for each scenario."""

import shutil
import tempfile
from pathlib import Path


def before_scenario(context, scenario):
    context.tmp_dir = Path(tempfile.mkdtemp())
    context.project_root = None
    context.last_response = None


def after_scenario(context, scenario):
    shutil.rmtree(context.tmp_dir, ignore_errors=True)
