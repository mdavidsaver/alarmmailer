# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import sys, os, os.path, atexit, time

_FMT = "%(asctime)s %(levelname)s:%(message)s"

class UserNotify(object):
    """Handle for the daemon (grandchild) process to send
    messages back to the parent.  Also used
    to indicate if the daemon encounters a fatal
    error which initializing.
    """
    def __init__(self, fd):
        self._fd = fd
    def msg(self, msg):
        self._fd.write('%s\n'%msg)
    def done(self, code, msg=None):
        if msg:
            self.msg(msg)
        self.msg('%d\n'%code)
        self._fd.close()
        if code:
            sys.exit(code)
    def exception(self, msg):
        if msg:
            self.msg(msg)
        import traceback
        traceback.print_exc(file=self._fd)
    def __enter__(self):
        return self
    def __exit__(self, A, B, C):
        if A or B or C:
            import traceback
            traceback.print_exception(A,B,C, file=self._fd)

class NullNotify(object):
    def msg(self, msg):
        print msg
    def done(self, code, msg):
        if msg:
            self.msg(msg)
        if code:
            sys.exit(code)
    def exception(self, msg):
        if msg:
            self.msg(msg)
        import traceback
        traceback.print_exc()
    def __enter__(self):
        return self
    def __exit__(self, A, B, C):
        pass

def rmfile(fn):
    LOG.info('Deleting %s', fn)
    try:
        os.unlink(fn)
    except:
        LOG.exception("Can't delete")
    LOG.info('After rm')

def daemonize(opts):
    """Fun double fork to free the daemon process
    of its parent.
    Returns a UserNotify instance which the grandchild
    can use to message the original parent, and
    let it know when to exit.
    """
    # Expand file names before fork to allow relative directories
    logfile = os.path.abspath(opts.log)
    pidfile = os.path.abspath(opts.pid)

    if opts.user:
        uname, _, gname = opts.user.partition(':')
        uid, gid = getuidgid(uname, gname)

    # A pipe to allow the parent to wait until the child
    # has successfully initialized (or not).
    RD, WR = os.pipe()
    c1pid = os.fork()
    if c1pid > 0:
        # original process
        os.close(WR)
        RD = os.fdopen(RD, 'r')
        print 'Waiting for daemon to initialize'
        c2pid = int(RD.readline())
        print 'daemon pid is',c2pid
        msg = '127'
        for l in RD.readlines():
            if l!='\n':
                msg = l
                print msg,
        RD.close()
        try:
            code = int(msg)
        except ValueError:
            code = 127
        if code:
            print 'Daemon failed to start.',code
        else:
            print 'Daemon started'
        sys.exit(code)

    # first child
    os.close(RD)

    os.chdir('/')
    os.setsid()
    os.umask(0002)

    c2pid = os.fork()
    if c2pid > 0:
        os.close(WR)
        sys.exit(0) # end first child

    WR = UserNotify(os.fdopen(WR, 'w'))
    WR.msg(str(os.getpid()))

    # Initialize logging before detaching stdin/out
    from logging.handlers import RotatingFileHandler
    root = logging.getLogger()
    fmt = logging.Formatter(_FMT)
    handler = RotatingFileHandler(logfile, maxBytes=100000, backupCount=5)
    handler.setFormatter(fmt)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    WR.msg("Logging initialized to %s"%logfile)

    ifd = os.open(os.path.devnull, os.O_RDONLY)
    ofd = os.open(os.path.devnull, os.O_WRONLY)

    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(ifd, sys.stdin.fileno())
    os.dup2(ofd, sys.stdout.fileno())
    os.dup2(ofd, sys.stderr.fileno())
    os.close(ifd)
    os.close(ofd)
    WR.msg("Output redirected")

    try:
        # will fail if PID file already exist (pidfile doubles as lockfile)
        FD = os.open(pidfile, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0644)
        # its ours, so try to cleanup properly
        atexit.register(rmfile, pidfile)
        os.write(FD, "%d"%os.getpid())
        os.close(FD)
    except:
        WR.exception("Failed to create pid file %s"%pidfile)
        WR.done(1)
        raise RuntimeError("shouldn't be here")

    # At this point we know we have exclusive control of the log
    WR.msg("PID written to %s"%pidfile)

    if opts.user:
        # fix permissions on log and pid files so we can
        # use them after dropping permissions
        os.chown(pidfile, uid, gid)
        os.chown(logfile, uid, gid)
        
        # drop permissions
        os.setgid(gid)
        os.setuid(uid)
        WR.msg('Switch permissions to %d:%d'%(os.getuid(),os.getgid()))

    return WR

def getuidgid(user, group=None):
    """Translate provided user (and optional group) into a uid,gid pair.

    >>> import os, pwd, grp
    >>> getuidgid('root')
    (0, 0)
    >>> getuidgid('0')
    (0, 0)
    >>> getuidgid('root', 'root')
    (0, 0)
    >>> getuidgid('root', '0')
    (0, 0)
    >>> getuidgid('0', 'root')
    (0, 0)
    >>> getuidgid('0', '0')
    (0, 0)
    >>> myuid = os.getuid()
    >>> myuser = pwd.getpwuid(myuid).pw_name
    >>> mygid = pwd.getpwuid(myuid).pw_gid
    >>> mygrp = grp.getgrgid(mygid).gr_name
    >>> smyuid, smygid = str(myuid), str(mygid)
    >>> getuidgid(myuser) == (myuid, mygid)
    True
    >>> getuidgid(smyuid) == (myuid, mygid)
    True
    >>> getuidgid(myuser, mygrp) == (myuid, mygid)
    True
    >>> getuidgid(myuser, smygid) == (myuid, mygid)
    True
    >>> getuidgid(smyuid, mygrp) == (myuid, mygid)
    True
    >>> getuidgid(smyuid, smygid) == (myuid, mygid)
    True
    >>> getuidgid(myuser, 'invalidgrp')
    Traceback (most recent call last):
        ...
    KeyError: 'getgrnam(): name not found: invalidgrp'
    >>> getuidgid('invaliduser', 'invalidgrp')
    Traceback (most recent call last):
        ...
    KeyError: 'getpwnam(): name not found: invaliduser'
    """
    import pwd, grp, os
    try:
        uent = pwd.getpwnam(user)
        uid, pgid = uent.pw_uid, uent.pw_gid
    except KeyError as e:
        try:
            uid = int(user) if user else os.getuid()
        except ValueError:
            raise e
        uent = pwd.getpwuid(uid)
        pgid = uent.pw_gid

    if not group:
        gid = pgid
    else:
        try:
            gid = grp.getgrnam(group).gr_gid
        except KeyError as e:
            try:
                gid = int(group)
            except ValueError:
                raise e
            gid = grp.getgrgid(gid).gr_gid

    return uid, gid

if __name__=='__main__':
    user, group = None, None
    if len(sys.argv)>2:
        user = sys.argv[2]
    if len(sys.argv)>3:
        group = sys.argv[3]

    if sys.argv[1]=='normal':
        N=daemonize()
        LOG.info('normal is normal')
        if user:
            N.msg('Dropping permissions: %s:%s'%(user,group))
            try:
                switchUID(user, group)
            except:
                N.exception('switchUID failed')
            else:
                N.msg('Switch to %d:%d'%(os.getuid(),os.getgid()))
        N.done(0,'Working')
        time.sleep(1)
        LOG.info('normal is done')
        sys.exit(0)

    elif sys.argv[1]=='fail':
        N=daemonize()
        N.done(5,'oh no!')

    elif sys.argv[1]=='doctest':
      import doctest
      doctest.testmod()

    else:
        print 'What is this',sys.argv[1],'of which you speak?'
        sys.exit(1)
