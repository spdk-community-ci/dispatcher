SPDK Community CI
=================

* Change Integration

  - GitHUB Action Workflows triggered by Gerrit Patchset Changes
  - Polls for patchsets
  - Pushes autorun status and artifacts

* System Software Environment

  - Containers, e.g. Docker, with all dependencies for building SPDK hosted
    on ghcr.io
  - System images, bootable ``.qcow2`` images, usable with qemu as well as
    physical machines, containing all dependencies for building and running
    SPDK. Images hosted in DigitalOcean spaces

* Runner Resources

  - Running in Docker (on GitHub hosted runner)
  - Running in qemu guest / virtual machine (via self-hosted runner)
  - Running on bare metal (via self-hosted runner)

This is a prototype of utilizing GitHub Actions (GHA) Workflows with Gerrit.
That is, allowing GHA Workflows to trigger when there are updates to patchsets
in Gerrit, and for Gerrit to retrieve status and artifacts from the GHA
workflows. How it works is briefly illustrated and described below.

Illustrated
-----------

Here is an attempt at visualizing how this is functioning::

  Script --> Gerrit Rest API -- ChangeInfo() --> Script.var.changes
    |  |
    |  +------- git ls-remote <target> --------> Script.var.existing
    |
    +-------> var.changes - var.existig -------> Script.var.changes_to_push
    |
    +---> for change in Script.var.changes_to_push
          |
          +--> git fetch <gerrit> --> pit push <target>
          |
          +--> GitHub Rest API ---> Trigger Workflow Dispatch

In a couple of words
--------------------

In a couple of words, changes are retrieve from Gerrit via its Rest API, changes
are then fetched and pushed via git, and finally, workflows in GitHub are
triggered via the GitHub Rest API.

<gerrit>
  This is the git-remote of the repository hosted in Gerrit where **changes**
  are fetched from.

<target>
  This is the git-remote of the repository hosted on GitHub where **changes**
  (patches branches) are pushed to.

This is handled by the ``dispatch.yml``, which either by manual trigger, or
via crontab-event, starts to checkout **this** CI-repository, and then checks
out the **spdk** repository and sets the **spdk** repository up, ensureing that
the above mentioned remotes are available, and then executesa script ``scripts/
gerrit_changes_to_github.py``, which takes care of the illustrated logic.

.. note::

   In the current prototype, then the scripts and workflows are out-of-tree
   and lives here in this **CI** repository. This could also be added to the
   repository itself, however, having it's own repository opens up for the
   potential that it can dispatch for multiple repositories.

Workflows
---------

The folder ``.github/workflows`` contains the workflow definitions. The workflow
``dispatch.yml`` takes care of the plumbing together of Gerrit and GitHub as
described above. Additionally, to actual workflows are available as references
of actually using it to test something.

dispatch.yml
  Retrieve changes from gerrit and push to SPDK mirror and trigger "autorun.yml"

autorun.yml - autorun.sh in a qemu guest
  This utilizes the ``autorun.sh`` script to invoke a unittest. It should
  be trivial to extend the scope of what is executed, e.g. scaling tests out
  to run in parallel. Status of all the jobs are combined in the job named
  "report" which is intended to report status back to gerrit. This executes on
  guest-guests using the Docker and .qcow images produced in build_images.yml.
  
build_images.yml - build Docker Image
  Build and push to ghcr.io

build_images.yml - build qcow2 Image
  Build .qcow2 image and push it to S3 compatible storage, currently a 1TB
  BackBlaze B2 bucket is utilized.

GitHUB Setup
------------

Service Account
~~~~~~~~~~~~~~~

Create a GitHUB service account, this account will be utilized to make pushes to
the SPDK repository mirror. It will also be the account that will be authorized
to vote in Gerrit.

Repository Secrets
~~~~~~~~~~~~~~~~~~

The dispatcher repository needs definition of the following **secrets**:

* GHPA_TOKEN
* S3_ENDPOINT_URL
* S3_KEY
* S3_SECRET

Organization Variables
~~~~~~~~~~~~~~~~~~~~~~

* SPDK_REPOS_NAME

FAQ
---

* Q1: What to do about this error?

  ::

    remote: Permission to {owner}/{repository}.git denied to {username}.
    fatal: unable to access 'https://github.com/{owner}/{repository}/': The requested URL returned error: 403

* Q1 Answer:

  - Create a service-account and ensure it is invited as a collaborator
  - Ensure sufficient permissions are granted to the user.
    When the **owner** is a personal account, they cannot be changed, however,
    default permissions suffice.
    When the **owner** is an organization account, they can be changed and
    ``write`` permissions must be granted.