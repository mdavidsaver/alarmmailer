# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import sys, os

from optparse import  OptionParser

from . import config

def main():
    parser = OptionParser()
    parser.add_option('-D','--daemonize', action='store_true', default=False,
                      help="Fork to background")
    parser.add_option('-T','--template', default=os.getcwd(), metavar='DIR',
                      help='Directory with email templates')
    parser.add_option('-P','--pid', default='daemon.pid', metavar='FILE',
                      help="Write daemon process id to this file")
    parser.add_option('-L','--log', default='daemon.log', metavar='FILE',
                      help="Write logs to this file")
    parser.add_option('-C','--config', default='daemon.conf', metavar='FILE',
                      help='Read configuration from this file')
    parser.add_option('-O','--check-config', action='store_true',
                      help='Exit after checking configuration')
    parser.add_option('-U','--user',metavar='USER[:GROUP]',
                      help='Switch to this user (and group) after starting')

    opts, args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    C = config.loadconfig(opts.config)
    if opts.check_config:
        sys.exit(0)

    import daemonize

    if opts.daemonize:
        done = daemonize.daemonize(opts.log, opts.pid)
        import signal
        def handler(sig,frame):
            import cothread
            cothread.Quit()
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    else:
        done = daemonize.NullNotify()

    if opts.user:
        try:
            # Drop permissions
            uname, _, gname = opts.user.partition(':')
            daemonize.switchUID(uname, gname)
            done.msg('Switch permissions to %d:%d'%(os.getuid(),os.getgid()))
        except:
            done.exception('Failed to switch user/group')
            raise

    LOG.info('initialize coselect')
    from cothread.coselect import select_hook
    select_hook()

    try:
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            from django.conf import settings
            settings.configure(INSTALLED_APPS=['alarmmail'],
                               TEMPLATE_DIRS=opts.template.split(':'),
                               TEMPLATE_DEBUG=True)

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

        import util

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
