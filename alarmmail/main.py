# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import os

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
        
    opts, args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    C = config.loadconfig(opts.config)

    done = None
    if opts.daemonize:
        import daemonize
        done = daemonize.daemonize(opts.log, opts.pid)
        import signal
        def handler(sig,frame):
            import cothread
            cothread.Quit()
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    LOG.info('initialize coselect')
    from cothread.coselect import select_hook
    select_hook()

    try:
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            from django.conf import settings
            settings.configure(INSTALLED_APPS=[], TEMPLATE_DIRS=opts.template.split(':'), TEMPLATE_DEBUG=True)

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
            for dest in pvg2dest[pvnodename]:
                node.add_notify(dest)

        import util

        # notify interested parties that we are running
        for dest in notifiers:
            if dest._conf.oninitial:
                dest.add(util.InternalEvent(util.RES_START))

        if done:
            done.msg("Waiting for PVs to connect")

        #TODO smarter wait...
        import cothread
        cothread.Sleep(C['main'].getdouble('initialwait', 1.0))

        # notify of initially disconnected
        for apv in pvs:
            if apv._prev is None:
                apv._notify.add(util.AlarmEvent(util.DummyValue(apv._name), util.RES_DISCONN, apv._conf))

        if done:
            done.done(0, 'Setup complete')
    except:
        if done:
            done.exception('Setup failed')
        raise
    done = True

    import cothread
    cothread.WaitForQuit()
