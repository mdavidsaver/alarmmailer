#!/usr/bin/env python

import logging
LOG = logging.getLogger(__name__)

import cothread
from cothread.coselect import select_hook
select_hook()

from . import config, notifier, util

from optparse import  OptionParser

class DummyLoader(object):
    def render_to_string(self, A, B):
        return 'Test message'
class TestNotifier(notifier.Notifier):
    def __init__(self, dest, serv):
        notifier.Notifier.__init__(self, dest, serv)
        self._loader = DummyLoader()

def sendmail(opts, C):
    LOG.info('Starting mail sender')

    mail = C['mail']
    mail.set('nosend', 'true' if opts.nosend else 'false')

    mailserv = notifier.EmailServer(mail)

    LOG.info('Starting destination node')

    dest = config.SectionProxy.fromArgs('testdest', **{'to':opts.to, 'from':opts.mfrom,
                                        'subject':'Test mail', 'delay':'1', 'holdoff':'2', 'groups':'x'})

    dest = config.DestNode(dest)

    dispatch = TestNotifier(dest, mailserv)

    LOG.info('Queue test mail')

    dispatch.add(util.InternalEvent(util.RES_START))

    cothread.Sleep(5)

    dispatch.close()
    mailserv.close()

    LOG.info('Done')

class CAX(object):
    severity, status = 0, 0
    timestamp = 0.0
    egu='arb.'
    def __init__(self, value, **kws):
        self._value = value
        for k,v in kws.iteritems():
            setattr(self, k, v)
    def __nonzero__(self):
        return self._value
    def __repr__(self):
        return str(self._value)
    __str__ = __repr__

def expand(opts, C):
    import time
    fname = opts.templatefile

    dest = config.SectionProxy.fromArgs('testdest', **{'to':opts.to, 'from':opts.mfrom,
                                        'subject':'Test mail', 'delay':'1', 'holdoff':'2', 'groups':'x'})

    dest.desc = {'pv:name:1:rbv':'pv:name:1:rbv'}
    util.djangosetup(opts)

    evts = [util.InternalEvent(util.RES_START)]

    now = time.time()-10.0
    
    D = [
      (CAX(1, name='pv:name:1:rbv', ok=True, timestamp=now+0), util.RES_NORMAL),
      (CAX(2, name='pv:name:1:rbv', ok=True, timestamp=now+2, severity=1, status=1), util.RES_ALARM),
      (CAX(5, name='pv:name:1:rbv', ok=True, timestamp=now+3, severity=2, status=1), util.RES_INCREASE),
      (CAX(2, name='pv:name:1:rbv', ok=True, timestamp=now+4, severity=1, status=1), util.RES_DECREASE),
      (CAX(1, name='pv:name:1:rbv', ok=True, timestamp=now+5), util.RES_NORMAL),
      (CAX(15,name='pv:name:1:rbv', ok=True, timestamp=now+6, severity=3, status=1), util.RES_ALARM),
      (CAX(1, name='pv:name:1:rbv', ok=True, timestamp=now+7), util.RES_NORMAL),
      (CAX(0, name='pv:name:1:rbv', ok=False, timestamp=now+8), util.RES_DISCONN),
      (CAX(1, name='pv:name:1:rbv', ok=True, timestamp=now+9), util.RES_NORMAL),
    ]

    [evts.append(util.AlarmEvent(d,d,r,dest)) for d,r in D]
    
    # the template context.
    ctxt = {'events':evts, 'notifier':dest, 'now':time.time()}

    from django.template import loader
    out = loader.render_to_string(fname, ctxt)

    print out
