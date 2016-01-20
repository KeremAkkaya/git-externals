#!/usr/bin/env python

from __future__ import unicode_literals

import os
import os.path
import shutil
import json
import sys

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

from cleanup_repo import git, svn, cleanup, chdir, checkout
from process_externals import unique_externals


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = ET.fromstring(data).findall('target')

    return unique_externals(targets)


def write_extfile(exts, filename='svn_externals'):
    with open(filename, 'wt') as fd:
        json.dump(exts, fd, indent=4)


def extract_repo_name(remote_name):
    return remote_name[1:remote_name.index('/', 1)]


def extract_repo_root(repo):
    output = svn('info', '--xml', repo)

    rootnode = ET.fromstring(output)
    return rootnode.find('./entry/repository/root').text


def branches():
    refs = git('for-each-ref', 'refs/heads', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def tags():
    refs = git('for-each-ref', 'refs/tags', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def get_layout_opts(repo):
    entries = set(svn('ls', repo).splitlines())

    opts = [
        '--trunk={}'.format('trunk' if 'trunk/' in entries else '.')
    ]

    if 'branches/' in entries:
        opts.append(
            '--branches=branches'
        )

    if 'tags/' in entries:
        opts.append(
            '--tags=tags'
        )

    return opts


def gittify_branch(repo, branch_name, obj, svn_server):
    gittified = set()

    with checkout(branch_name, obj):
        externals = get_externals(os.path.join(svn_server, repo))

        if len(externals) > 0:
            with chdir('..'):
                for ext in externals:
                    # FIXME: convert blocked externals revision to commit sha with git svn find-rev
                    repo_name = extract_repo_name(ext['location'])
                    gittified_externals = gittify(repo_name, svn_server)
                    gittified.update(gittified_externals)

            write_extfile(externals)
            git('add', 'svn_externals')
            git('commit', '-m', 'gittify: create svn_externals file')

    return gittified


def gittify(repo, svn_server, basename_only=True):
    gittified = set([repo])

    # check if already gittified
    if os.path.exists(repo):
        return gittified

    repo_name = repo
    if basename_only:
        repo_name = os.path.basename(repo)

    tmprepo = '{}.tmp'.format(repo_name)

    remote_repo = os.path.join(svn_server, repo)
    layout_opts = get_layout_opts(remote_repo)
    is_std = len(layout_opts) == 3

    if not os.path.exists(tmprepo):
        # FIXME: handle authors file for mapping SVN users to Git users
        # layout_opts must come before the arguments
        args = ['svn', 'clone', '--prefix=origin/'] + layout_opts + [remote_repo, tmprepo]
        git(*args)

        branch_repo = os.path.join(repo, 'branches') if is_std else None
        cleanup(tmprepo, False, branch_repo)

    with chdir(tmprepo):
        for branch in branches():
            if not is_std:
                subrepo = repo
            elif branch != 'master':
                subrepo = os.path.join(repo, 'branches', branch)
            else:
                subrepo = os.path.join(repo, 'trunk')

            # we've already created a local branch for each
            # origin branch with cleanup
            external_gittified = gittify_branch(subrepo, branch, None, svn_server)
            gittified.update(external_gittified)

        for tag in tags():
            subrepo = os.path.join(repo, 'tags', tag)
            external_gittified = gittify_branch(subrepo, tag, tag, svn_server)

            # following should work, but not properly tested yet :)
            if len(external_gittified) > 0:
                gittified.update(gittify_branch)
                git('tag', '-d', tag)
                git('tag', tag, tag)

            git('branch', '-D', tag)

    git('clone', '--bare', tmprepo, repo_name)
    with chdir(repo_name):
        git('remote', 'rm', 'origin')

    shutil.rmtree(tmprepo)

    return gittified


if __name__ == '__main__':
    for r in sys.argv[1:]:
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        gittify(repo, root)
