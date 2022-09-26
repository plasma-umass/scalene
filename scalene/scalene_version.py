"""Current version of Scalene; reported by --version."""

import datetime
import os

def get_commit_date(fname):
    """Return the git commit date of this file, as a Unix timestamp."""
    # Adapted from https://stackoverflow.com/a/69812342/335756
    import git # gitpython library
    import os
    from pathlib import Path

    repo_path = "."
    repo = git.Repo(repo_path)

    n = repo.tree()[fname]
    filepath = Path(repo.working_dir) / n.path
    unixtime = repo.git.log(
        "-1", "--format='%at'", "--", n.path
    ).strip("'")
    if not unixtime.isnumeric():
        raise ValueError(
            f"git log gave non-numeric timestamp {unixtime} for {n.path}"
        )
    return int(unixtime)


scalene_version = "1.5.13"

scalene_date = datetime.datetime.fromtimestamp(get_commit_date("scalene/scalene_version.py")).strftime("%Y/%m/%d")
