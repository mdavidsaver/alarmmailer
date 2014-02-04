# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import time

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import util

#import django.template.loader as loader

class EmailServer(util.WorkerQueue):
    def __init__(self, S):
        util.WorkerQueue.__init__(self,
                                  delay=S.getdouble('delay',30.0),
                                  holdoff=S.getdouble('holdoff',30.0),
                                  qsize=S.getint('queueSize',10))
        import smtplib
        self.timeout = S.getint('timeout', 15)
        self.server = S.get('server','localhost')
        self.port = S.get('port', None)
        self.nosend = S.getboolean('nosend', False)
        proto = S.get('proto', 'ESMTP')
        if proto not in ['ESMTP']:
            raise ValueError('mail protocol %s not supported'%proto)
        self._transport = smtplib.SMTP

    def process(self, evts, overflow):
        LOG.info('Sending %d mails',len(evts))
        if overflow:
            LOG.warning('Lost some mails from queue overflow')
        if self.nosend:            
            for mfrom, mto, msg in evts:
                LOG.debug('From: %s To: %s\n%s\n', mfrom, mto, msg)
            return

        conn = self._transport(self.server, self.port, timeout=self.timeout)
        for mfrom, mto, msg in evts:
            conn.sendmail(mfrom, mto, msg)
        conn.quit()

class Notifier(util.WorkerQueue):
    def __init__(self, C, serv):
        util.WorkerQueue.__init__(self,
                                  delay=C.delay,
                                  holdoff=C.holdoff,
                                  qsize=C.qsize)
        from django.template import loader
        self._conf, self.server = C, serv
        self._loader = loader

    def process(self, evts, overflow):
        LOG.info('%s processing %d events', self, len(evts))

        msg = MIMEMultipart('alternative')

        # take mail header directly from configuration
        msg['To'] = ', '.join(self._conf.mto)
        msg['From'] = self._conf.mfrom
        msg['Subject'] = self._conf.msubject%{'cnt':len(evts)}

        # the template context.
        ctxt = {'events':evts, 'notifier':self._conf, 'now':time.ctime()}
        # render to text for both mime types
        filename = self._conf.plain
        msg.attach(MIMEText(self._loader.render_to_string(filename, ctxt), 'plain'))
        filename = self._conf.html
        msg.attach(MIMEText(self._loader.render_to_string(filename, ctxt), 'html'))

        if not self.server.add((self._conf.mto, self._conf.mfrom, msg)):
            LOG.error("Failed to Q '%s' to: %s", msg['Subject'], msg['To'])

    def __repr__(self):
        return 'Notifier(%s)'%self._conf.name
