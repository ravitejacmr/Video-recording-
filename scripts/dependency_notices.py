"""Collect installed Python distribution license metadata beside the app."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for dist in distributions():
    for file in dist.files or []:
        if '.dist-info/' in str(file) and any(s in str(file).lower() for s in ('license', 'copying', 'notice')):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = root / dist.metadata['Name'] / Path(file).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
