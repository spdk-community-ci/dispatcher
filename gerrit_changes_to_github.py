#!/usr/bin/env python3
"""
Changes from Gerrit to GitHUB
=============================

Pushes branches containing patch-sets from Gerrit to a 'target' git remote and triggers
workflow-dispatch on GitHub.

* Retrieve change-information from Gerrit via REST API

* Transfer the change from Gerrit to GitHub

  - git fetch from: args.git_remote_gerrit_name
  - git push to: args.git_remote_target_name

* Trigger workflow on GitHUB Using the REST API

  - Provide 'changes/xx/yyyyy/zz' as input to the workflow-dispatch trigger

These are the command-line arguments of this script, where the script assumes that
'args.git_repository' is a path to a git repository with that has the following remotes:

args.git_remote_gerrit_name
  The name of the remote containing the patchsets / changes as hosted in Gerrit.

args.git_remote_target_name
  The repository on e.g. GitHUB, GitLAB etc. that you want changes pushed **to**

The names of the branches, as they will appear on the 'target' remote is made avaialble
in the file branches.json.

In addition, for the part that uses the GitHub API to trigger workflow-dispatch then the
script assumes that the following environment variables are available:

GHPA_TOKEN
  This should be setup as a repository-secret and contain a GitHub Personal Access token
  of an account with sufficient permissions to 'args.github_repos_name'.

GITHUB_REPOSITORY
  This must provide the full name of the GitHub repository e.g. ``owner/
  repository_name``, this is set by GitHub, but if you execute this locally, the ensure
  that it is set accordingly. This is the name of the CI repository, not the repository
  with changes etc.

Caveat
------

The Gerrit REST API returns a maximum of 500 changes per request, ordered by most recent
update. If there are more than 500 changes, the 501st least recently updated change will
not be retrieved or processed by this script.

The changes are processed in the order they are retrieved, consequently then change
501 least recently updated will be "starved". This can be fixed by modifying the range
of received changes, however, has been kept out for this initial prototype of the
integration.
"""
import argparse
import json
import logging as log
import os
import re
import sys
from pathlib import Path
from pprint import pprint
from subprocess import CompletedProcess, run
from typing import Dict, List, Optional, Tuple

import requests

REGEX_BRANCHES = (
    r"(?P<ref>[a-z0-9]+)\s+refs\/heads\/changes\/"
    r"(?P<dir>\d+)\/(?P<change_nr>\d+)\/(?P<patch_nr>\d+)"
)


def setup_default_logger(log_file: Path):
    """Setup the default logger to log to file and console"""

    logger = log.getLogger()
    logger.setLevel(log.DEBUG)

    formatter = log.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = log.FileHandler(str(log_file))
    file_handler.setLevel(log.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = log.StreamHandler(sys.stdout)
    console_handler.setLevel(log.INFO)
    console_handler.setFormatter(formatter)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def run_cmd(cmd: str, cwd: Optional[Path] = None) -> CompletedProcess:
    """
    Wrapping subprocess.run() with default arguments and logging
    """

    if not cwd:
        cwd = Path.cwd()

    log.info(f"Running cmd({cmd})")
    proc = run(cmd, capture_output=True, shell=True, text=True, cwd=cwd)
    if proc.returncode:
        log.error(f"Failed executing cmd({cmd}) got returncode({proc.returncode})")
        log.error(f"{proc.stderr}")
        log.error(f"{proc.stdout}")

    return proc


def parse_args():
    parser = argparse.ArgumentParser(
        description="Retrieve untested changes from Gerrit"
    )

    parser.add_argument(
        "--gerrit-api-url",
        type=str,
        help="URL to utilize to query the Gerrit REST API for ChangeInfo",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of changes to process (fetch/push/trigger)",
        default=5,
    )
    parser.add_argument(
        "--log", type=Path, help="Path to log-file", default=Path.cwd() / "gc.log"
    )

    parser.add_argument(
        "--git-repository-path", type=Path, help="Local path to git repository clone"
    )
    parser.add_argument(
        "--git-remote-gerrit-name",
        type=str,
        help="Name of the remote hosted by gerrit with changes",
        default="gerrit",
    )
    parser.add_argument(
        "--git-remote-target-name",
        type=str,
        help="Name of the git-remote that you want to push changes to",
        default="target",
    )

    parser.add_argument(
        "--workflows",
        type=str,
        nargs="+",
        help="Name of the one or more workflow(s) to trigger; e.g. 'myworkflow.yml'",
    )

    return parser.parse_args()


def gerrit_changeinfo_via_rest_api(args) -> Optional[List[str]]:
    """
    Returns a list of refs, retrieved via the Gerrit Rest API, or None on error.
    """

    if (response := requests.get(args.gerrit_api_url)).status_code != 200:
        log.error(
            f"Failed to retrieve changes. HTTP Status Code: {response.status_code}"
        )
        return None

    response_text = response.text[4:]

    remotes = set()
    refs = []
    for change in json.loads(response_text):
        for sha, meta in change.get("revisions", {}).items():
            remote = meta.get("fetch", {}).get("anonymous http", {}).get("url", None)
            if not remote:
                log.error(f"No remote for change({change})")
                return None

            remotes.add(remote)
            log.info(f"change: sha({sha}), meta({meta.get('fetch')})")

            if not (ref := meta.get("ref", None)):
                log.error(f"Unexpected data for change({change})")
                return None

            refs.append(str(ref))

    # If there are changes, they should all be for a single anonymous gerrit remote
    if len(remotes) > 1:
        log.error(f"Unexpected remotes({remotes})")
        return None

    # Be verbose; it makes it easier to understand what is going on by inspecting the
    # output of the command in a CI log and even when running it manually
    for ref in refs:
        log.info(f"Got ref({ref}) via REST API")
    log.info(f"A total of {len(refs)} changes retrieved.")
    if len(refs) >= args.limit:
        log.info(
            f"There is likely more to process, as n equals the limit({args.limit})"
        )

    return refs


def branches_on_target(args) -> Optional[List[Tuple[str, Dict]]]:
    """Retrieve branches carrying changes"""

    cmd = f"git ls-remote --branches {args.git_remote_target_name}"
    if (proc := run_cmd(cmd, cwd=args.git_repository_path)).returncode:
        return None

    return [
        (
            f"changes/{info['dir']}/{info['change_nr']}/{info['patch_nr']}",
            dict(info.groupdict()),
        )
        for branch in proc.stdout.strip().splitlines()
        if (info := re.match(REGEX_BRANCHES, branch.strip()))
    ]


def changes_apply_filter(args, changes, branches) -> List[str]:
    """Drop changes for which branches already exist"""

    filtered = []
    for change in changes:
        if [branch for branch, _ in branches if branch in change]:
            continue

        filtered.append(change)

    log.info(f"Dropped({len(changes) - len(filtered)}) changes, left({len(filtered)})")

    return filtered


def is_repository_usable(args):
    """Verify that the cloned repository(args.repository) has the expected remotes"""

    proc = run_cmd("git remote -v", cwd=args.git_repository_path)
    if proc.returncode:
        return False

    log.info(f"proc.stdout({proc.stdout})")

    got_gerrit = got_target = False
    for line in proc.stdout.splitlines():
        torn = line.split()
        if len(torn) != 3:
            continue

        name, url, direction = torn
        if "fetch" in direction and args.git_remote_gerrit_name == name:
            got_gerrit = True
            continue

        if "push" in direction and args.git_remote_target_name == name:
            got_target = True
            continue

    log.info(f"got_gerrit({got_gerrit}), got_target({got_target})")

    return got_gerrit and got_target


def main(args):
    """Entry-point for the script; see parse_args() for the arguments"""

    setup_default_logger(args.log)

    log.info("Running with the following args.")
    for arg, value in vars(args).items():
        log.info(f"{arg}: {value}")

    if args.limit > 500:
        log.error(f"Gerrit can return no more than 500 changes per. request")
        return 1

    if not is_repository_usable(args):
        log.error(f"Local repository({args.git_repository_path}) not usable")
        return 1

    if (ghci_repository := os.getenv("GITHUB_REPOSITORY", None)) is None:
        log.error(
            "GITHUB_REPOSITORY is not set; "
            "should contain full name of the CI Repository on GitHub"
        )
        return 1

    if (ghpa_token := os.getenv("GHPA_TOKEN", None)) is None:
        log.error("GHPA_TOKEN is not set; should contain personal access token")
        return 1

    if (changes := gerrit_changeinfo_via_rest_api(args)) is None:
        log.error("Failed retrieving changes")
        return 1

    if (branches := branches_on_target(args)) is None:
        log.error("Failed retrieving branches")
        return 1

    if (changes_to_push := changes_apply_filter(args, changes, branches)) is None:
        log.error("Failed filtering changes")
        return 1

    for count, ref in enumerate(changes_to_push, 1):
        if count > args.limit:
            log.info(f"Pushed count({count}), stopping due to limit({args.limit})")
            break

        # git-fetch the change from Gerrit and git-push it to GitHub
        dst = ref.replace("refs/", "refs/heads/")
        for cmd in [
            f"git fetch {args.git_remote_gerrit_name} {ref}",
            f"git push {args.git_remote_target_name} FETCH_HEAD:{dst} --no-verify",
        ]:
            proc = run_cmd(cmd, cwd=args.git_repository_path)
            if proc.returncode:
                log.error("Stopping due to errors during fetch/push")
                return proc.returncode

        # Trigger the workflow-dispatch event with the branch name as input
        for workflow in args.workflows:
            url = (
                f"https://api.github.com/repos/{ghci_repository}"
                f"/actions/workflows/{workflow}/dispatches"
            )
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {ghpa_token}",
            }
            data = {"ref": "main", "inputs": {"branch": ref.replace("refs/", "")}}
            log.info(f"Triggering workflow-dispatch via url({url}) and data({data})")

            response = requests.post(url, headers=headers, json=data)
            if response.status_code != 204:
                log.error(f"status_code({response.status_code}); '{response.text}'")
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(parse_args()))
