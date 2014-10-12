# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import sys, os

from . import config, mailtest, util

def rundaemon(opts, C):
    import daemonize

    if opts.daemonize:
        done = daemonize.daemonize(opts)
        import signal
        def handler(sig,frame):
            import cothread
            cothread.Quit()
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    else:
        done = daemonize.NullNotify()

    LOG.info('initialize coselect')
    from cothread.coselect import select_hook
    select_hook()

    import util

    try:
        util.djangosetup(opts)

        from . import notifier

        mailer = notifier.EmailServer(C['mail'])
#        done.done(0, 'Setup complete')

        notifiers = [notifier.Notifier(destnode, mailer) for destnode in C['dest'].itervalues()]

        # build the reverse mapping from PV Group config to destination        
        pvg2dest = {}
        for dest in notifiers:
            for pvg in dest._conf.groups:
                try:
                    L = pvg2dest[pvg]
                except KeyError:
                    L = pvg2dest[pvg] = []
                L.append(dest)

        from . import pv

        pvs = []
        for pvnodename, pvnode in C['pv'].iteritems():
            node = pv.NotifyFanout()
            pvs.extend([pv.PV(name, pvnode, node) for name in pvnode.pvs])
            try:
                dests = pvg2dest[pvnodename]
            except KeyError:
                LOG.warning("PV group %s not referenced by any destinations", pvnodename)
            else:
                for dest in dests:
                    node.add_notify(dest)

        # notify interested parties that we are running
        for dest in notifiers:
            if dest._conf.oninitial:
                dest.add(util.InternalEvent(util.RES_START))

        done.msg("Waiting for PVs to connect")

        #TODO smarter wait...
        import cothread
        cothread.Sleep(C['main'].getdouble('initialwait', 1.0))

        # notify of initially disconnected
        ndis = 0
        for apv in pvs:
            if apv._prev is None:
                ndis += 1
                apv._notify.add(util.AlarmEvent(util.DummyValue(apv._name), None, util.RES_DISCONN, apv._conf))

        LOG.info("%d disconnected PVs", ndis)

        done.done(0, 'Setup complete')
    except:
        done.exception('Setup failed')
        raise
    done = True

    import cothread
    cothread.WaitForQuit()

def getopts():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('-T','--template', default=os.getcwd(), metavar='DIR',
                      help='Directory with email templates')
    parser.add_argument('-L','--log', default='mailer.log', metavar='FILE',
                      help="Write logs to this file")
    parser.add_argument('-C','--config', default='mailer.conf', metavar='FILE',
                      help='Read configuration from this file')
    parser.add_argument('-O','--check-config', action='store_true',
                      help='Exit after checking configuration')

    subp = parser.add_subparsers()

    # Main daemon
    daemon = subp.add_parser('daemon', help='Notification daemon')
    daemon.add_argument('-D','--daemonize', action='store_true', default=False,
                      help="Fork to background")
    daemon.add_argument('-P','--pid', default='daemon.pid', metavar='FILE',
                      help="Write daemon process id to this file")
    daemon.add_argument('-U','--user',metavar='USER[:GROUP]',
                      help='Switch to this user (and group) after starting')
    daemon.set_defaults(action=rundaemon)

    # test mail sender
    mtest = subp.add_parser('mailtest', help='Test email configuration')
    mtest.add_argument('--from', default='testmail@localhost', dest='mfrom',
                       help='Source address')
    mtest.add_argument('--to', help='Destination address(es)')
    mtest.add_argument('--nosend', action='store_true', default=False, help="Print message without sending")
    mtest.set_defaults(action=mailtest.sendmail)

    # test template expander
    ttest = subp.add_parser('expandtest', help='Test template expander')
    ttest.add_argument('--from', default='testmail@localhost', dest='mfrom',
                       help='Source address')
    ttest.add_argument('--to', default='someone@xyz', help='Destination address(es)')
    ttest.add_argument('templatefile')
    ttest.set_defaults(action=mailtest.expand)
    
    return parser.parse_args()

def main(opts=None):
    if opts is None:
        opts = getopts()
    logging.basicConfig(level=logging.DEBUG)

    C = config.loadconfig(opts.config)
    if opts.check_config:
        sys.exit(0)

    opts.action(opts, C)
