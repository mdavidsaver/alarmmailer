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
        traceback.print_exc(file=self._fd)
    def __enter__(self):
        return self
    def __exit__(self, A, B, C):
        pass

def daemonize(logfile='log', pidfile='pid'):
    """Fun double fork to free the daemon process
    of its parent.
    Returns a UserNotify instance which the grandchild
    can use to message the original parent, and
    let it know when to exit.
    """
    # Expand file names before fork to allow relative directories
    logfile = os.path.abspath(logfile)
    pidfile = os.path.abspath(pidfile)
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
    os.umask(0)

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
        atexit.register(os.unlink, pidfile)
        os.write(FD, "%d"%os.getpid())
        os.close(FD)
    except:
        WR.exception("Failed to create pid file %s"%pidfile)
        WR.done(1)
    # At this point we know we have exclusive control of the log
    WR.msg("PID written to %s"%pidfile)

    return WR

if __name__=='__main__':
    if sys.argv[1]=='normal':
        N=daemonize()
        N.done(0,'Working')
        LOG.info('normal is normal')
        time.sleep(1)
        LOG.info('normal is done')
        sys.exit(0)

    elif sys.argv[1]=='fail':
        N=daemonize()
        N.done(5,'oh no!')

    else:
        print 'What is this',sys.argv[1],'of which you speak?'
        sys.exit(1)
