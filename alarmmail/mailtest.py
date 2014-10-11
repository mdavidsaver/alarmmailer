#!/usr/bin/env python

import logging
LOG = logging.getLogger(__name__)

import cothread
from cothread.coselect import select_hook
select_hook()

from alarmmail import config, notifier, util

from optparse import  OptionParser

class DummyLoader(object):
    def render_to_string(self, A, B):
        return 'Test message'
class TestNotifier(notifier.Notifier):
    def __init__(self, dest, serv):
        notifier.Notifier.__init__(self, dest, serv)
        self._loader = DummyLoader()

def main(opts, C):
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
