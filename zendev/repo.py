import re
import sys

from git.exc import GitCommandError
from termcolor import colored
import gitflow.core
import py
import github
import time
import json

from .log import error, info
from .utils import is_git_repo, memoize


is_github = re.compile('^[^\/\s@]+\/[^\/\s]+$').match


class Repository(object):
    """
    A repository.
    """
    def __init__(self, localpath, path, repo, name="", ref="develop"):
        self.name = name or localpath
        self.path = py.path.local(path)
        self.reponame = str(repo)
        self.url = self._proper_url(repo)
        self.ref = ref
        self.progress = None
        self._repo = None

    def _proper_url(self, url):
        if is_github(url):
            return 'git@github.com:' + url
        return url

    @property
    @memoize
    def branch(self):
        try:
            return self.repo.repo.active_branch.name
        except TypeError:
            head = self.repo.repo.head
            sha, target = head._get_ref_info(head.repo, head.path)
            return sha

    @property
    @memoize
    def hash(self):
        try:
            return self.repo.repo.head.ref.object.hexsha
        except TypeError:
            head = self.repo.repo.head
            sha, target = head._get_ref_info(head.repo, head.path)
            return sha

    @property
    @memoize
    def remote_branch(self):
        tracking = self.repo.repo.active_branch.tracking_branch()
        if tracking:
            return tracking.name

    @property
    @memoize
    def remote_branches(self):
        """ return a list of all remote branches """
        return self.repo.branch_names(remote=True)

    @property
    @memoize
    def local_branches(self):
        """ return a list of all local branches """
        return self.repo.branch_names()

    @property
    @memoize
    def tag_names(self):
        """
        Return a list of all tags.
        """
        return [tag.name for tag in self.repo.repo.tags]

    @property
    @memoize
    def changes(self):
        staged = unstaged = untracked = False
        lines = self.repo.repo.git.status('-z', porcelain=True).split('\x00')
        for char in (x[:2] for x in lines):
            if char.startswith('?'):
                untracked = True
            elif char.startswith(' '):
                unstaged = True
            elif char:
                staged = True
        return staged, unstaged, untracked

    @property
    @memoize
    def repo(self):
        self.initialize()
        return self._repo

    def checkout(self, ref):
        if ref != self.branch:
            self.repo.repo.git.checkout(ref)

    def clone(self, shallow=False):
        kwargs = {}
        if shallow:
            kwargs['depth'] = 1
        if self.ref:
            kwargs['branch'] = self.ref
        if self.path.check():
            raise Exception("Something already exists at %s. "
                            "Remove it first." % self.path)
        else:
            self.path.dirpath().ensure(dir=True)
            try:
                gitrepo = gitflow.core.Repo.clone_from(
                    self.url,
                    str(self.path),
                    progress=self.progress,
                    **kwargs)
            except GitCommandError:
                # Can't clone a hash, so clone the entire repo and check out
                # the ref
                gitrepo = gitflow.core.Repo.clone_from(
                    self.url,
                    str(self.path),
                    progress=self.progress)
                gitrepo.git.checkout(self.ref)
            self._repo = gitflow.core.GitFlow(gitrepo)
            if not shallow:
                self.initialize()

    def shallow_clone(self):
        return self.clone(shallow=True)

    def start_feature(self, name, base=None):
        # Note: the called routine is monkey-patched
        self.repo.create('feature', name, base, None)

    def publish_feature(self, name):
        self.repo.publish('feature', name)

    def finish_feature(self, name):
        feature_name = "feature/%s" % name
        origin_feature_name = "origin/feature/%s" % name

        if feature_name in self.local_branches:
            self.repo.finish('feature', name, fetch=True, rebase=False,
                             keep=False, force_delete=True, tagging_info=None)
        # XXX repo (GitFlow) doesn't push remote repo delete currently :(
        if origin_feature_name in self.remote_branches:
            self.repo.origin().push(":" + feature_name)

    def stash(self):
        self.repo.git.stash('-u')

    def apply_stash(self):
        self.repo.git.stash('apply')

    def fetch(self):
        self.repo.git.fetch(all=True)

    def message(self, msg):
        print colored('==>', 'blue'), colored(msg, 'white')

    def merge_from_remote(self):
        try:
            active_branch = self.repo.repo.active_branch
        except TypeError:
            # We're detached
            return
        local_name = active_branch.name
        tracking = active_branch.tracking_branch()
        remote_name = tracking.name if tracking else local_name

        if self.repo.is_merged_into(remote_name, local_name):
            # Nothing to do
            return
        self.message("Changes found in %s:%s! Rebasing %s..." % (
            self.name, remote_name, local_name))
        weStashed = False
        if any(self.changes):
            weStashed = True
            self.stash()
        self.repo.git.rebase(remote_name, output_stream=sys.stderr)
        try:
            if weStashed:
                self.apply_stash()
        except GitCommandError:
            pass

    def push(self):
        try:
            active_branch = self.repo.repo.active_branch
        except TypeError:
            # We're detached
            return
        local_name = active_branch.name
        remote = self.repo.origin()
        output = self.repo.git.rev_list(local_name, '--not', '--remotes')
        if output:
            self.message(("%s local commits in %s:%s need to be pushed.  "
                         "Pushing...") % (output.count('\n')+1, self.name,
                                          local_name))
            self.repo.git.push(remote, local_name, output_stream=sys.stderr)

    def create_feature(self, name):
        fname = "feature/%s" % name
        ofname = "origin/feature/%s" % name

        local = fname in self.local_branches
        remote = ofname in self.remote_branches

        if local and remote:
            return

        if not local and remote:
            self.fetch()
        elif local and not remote:
            self.publish_feature(name)
        else:
            self.start_feature(name)
            self.publish_feature(name)

    def changelog(self, fromref, toref):
        return self.repo.git.log(
            "%s..%s" % (fromref, toref), "--pretty=format:%h - %an, %ar : %s")

    def create_pull_request(self, feature_name, body='', base='develop'):
        staged, unstaged, untracked = self.changes

        if unstaged:
            error("uncommited changes in: %s" % self.name)
            return

        branch = "feature/%s" % feature_name
        url = self.repo.repo.remote().url
        line = url.rsplit(":", 1)[-1]
        owner, repo = line.split('/')[-2:]
        repo = repo.split()[0]
        if repo.endswith('.git'):
            repo = repo[:-4]

        self.push()
        time.sleep(1)
        self.message("Posting pull request")
        header, response = github.perform(
            "POST",
            "/repos/{0}/{1}/pulls".format(owner, repo),
            data=json.dumps({
                "title": "Please review branch %s" % branch,
                "body": body,
                "head": branch,
                "base": base
            }))
        if 'html_url' in response:
            info("Pull Request: %s" % response['html_url'])
        elif response['message'] == 'Validation Failed':
            for e in response['errors']:
                error("Error: %s" % e.get('message', json.dumps(e, indent=2)))

    def initialize(self):
        if not self._repo and is_git_repo(self.path):
            self._repo = gitflow.core.GitFlow(self.path.strpath)
        if self._repo and not self._repo.is_initialized():
            py.io.StdCaptureFD.call(self._repo.init)
