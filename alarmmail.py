#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cothread
from cothread import cosocket

cosocket.socket_hook()

import time, sys, os, traceback, smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cothread import catools as ca

if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    from django.conf import settings
    settings.configure(INSTALLED_APPS=[], TEMPLATE_DIRS=['.'], TEMPLATE_DEBUG=True)

import django.template.loader as loader

from ConfigParser import SafeConfigParser as ConfigParser, NoOptionError, NoSectionError

_SEVR = {0:'No Alarm', 1:'Minor   ', 2:'Major   ', 3:'Invalid ', 4:'Disconn.'}
def SEVR(sevr):
    return _SEVR.get(sevr, 'Unknown')

class AlarmEvent(object):
    def __init__(self, data, reason, config):
        self._data, self.reason, self.section = data, reason, config
        self.rxtimestamp = time.time()
        if not data.ok:
            data.severity = 4
            data.status = 0
            data.timestamp = self.rxtimestamp
    def __getattr__(self, key):
        return getattr(self._data, key)
    @property
    def sevr(self):
        return self._data.severity
    @property
    def severity(self):
        return SEVR(self._data.severity)
    @property
    def value(self):
        return self._data
    @property
    def time(self):
        return time.ctime(self._data.timestamp)
    @property
    def rxtime(self):
        return time.ctime(self._data.rxtimestamp)
    def __repr__(self):
        return 'AlarmEvent(%s, %s)'%(self._data, self.reason)

class InternalEvent(object):
    def __init__(self, reason):
        self.reason = reason
        self.name = '<internal>'
        self.value = None
        self.sevr = 5
        self.severity = "Internal"
        self.status = 0
        self.timestamp = self.rxtimestamp = time.time()
        self.time = self.rxtime = self.ctime(self.timestamp)

class AlarmReason(object):
    def __init__(self, code, msg):
        self.code, self.message = code, msg
    def __str__(self):
        return '%s (%d)'%(self.message, self.code)
    def __repr__(self):
        return 'AlarmReason(%d, "%s")'%(self.code, self.message)
RES_NORMAL = AlarmReason(0, "Alarm cleared")
RES_ALARM = AlarmReason(1, "Alarm")
RES_INCREASE = AlarmReason(2, "Severity incresed")
RES_DECREASE = AlarmReason(3, "Severity decresed")
RES_DISCONN = AlarmReason(4, "Connection lost")
RES_QFULL = AlarmReason(5, "Queue full")
RES_LOST = AlarmReason(6, "Lost Events")

_dft_msg = "%(severity)s\t%(name)s (%(value)s at %(time)s)"

class SectionProxy(object):
    _True = ['t','y','true','yes']
    def __init__(self, conf, sect):
        self._conf, self._sect = conf, sect

    @property
    def name(self):
        return self._sect

    def __contains__(self, key):
        return self._conf.has_option(self._sect, key)

    def get(self, key, default=None, vars={}):
        try:
            return self._conf.get(self._sect, key, False, vars)
        except (NoOptionError, NoSectionError):
            return default

    def getboolean(self, key, default=None, vars={}):
        try:
            return self._conf.get(self._sect, key, False, vars).lower() in self._True
        except (ValueError, NoOptionError, NoSectionError):
            return default
    getbool = getboolean

    def getint(self, key, default=None, vars={}):
        try:
            return int(self._conf.get(self._sect, key, False, vars))
        except (ValueError, NoOptionError, NoSectionError):
            return default

    def getdouble(self, key, default=None, vars={}):
        try:
            return float(self._conf.get(self._sect, key, False, vars))
        except (ValueError, NoOptionError, NoSectionError):
            return default

class AlarmPV(object):
    def __init__(self, pvname, conf, notify):
        self._name, self._conf, self.notify = pvname, conf, notify
        self._prev = None
        self._sub = ca.camonitor(pvname, self._update,
                                 format=ca.FORMAT_TIME,
                                 count=1,
                                 notify_disconnect=True)

    def close(self):
        self._sub.close()

    def _update(self, data):
        """Decide if an alarm is in effect and
        classify it
        """
        P = self._prev
        self._prev = data

        if data.update_count!=1:
            self.notify.add(AlarmEvent(data, RES_LOST))

        reason = None
        if P is None:
            # Initial update
            if self._conf.getbool('alarminitial',False):
                if not data.ok:
                    reason = RES_DISCONN
                if data.severity!=0:
                    reason = RES_ALARM
            return

        if data.ok:
            if P.severity and not data.severity:
                reason = RES_NORMAL
            elif not P.severity and data.severity:
                reason = RES_ALARM
            elif P.severity < data.severity:
                reason = RES_INCREASE
            elif P.severity > data.severity:
                reason = RES_DECREASE
        elif P.ok:
            reason = RES_DISCONN

        if reason is not None:
            self.notify.add(AlarmEvent(data, reason, self._conf))

class Notifier(object):
    _STOP = object()
    def __init__(self, conf):
        self._conf = conf
        self._V = conf.get('print',False)
        self._SP = conf.getdouble('maxperiod', 10.0)
        self._BT = conf.getdouble('holdoff', 3.0)
        self._N  = conf.getint('Qsize', 10)

        self._email = conf.getboolean('email', False)
        self._email_nosend = conf.getboolean('email.nosend', False)

        self._Q, self._oflow = [], False
        self.waitn = cothread.Event(auto_reset=False)
        self.sleep = cothread.Event(auto_reset=False)
        self.T = cothread.Spawn(self._run)

    def close(self):
        self.waitn.Signal(self._STOP)
        self.sleep.Signal(self._STOP)
        self.T.Wait()

    def add(self, evt):
        if len(self._Q)>self._N:
            if not self._oflow:
                self._oflow = True
                evt = InternalEvent(RES_QFULL)
            else:
                return # Drop further events

        else:
            self._oflow = False

        self._Q.append(evt)
        self.waitn.Signal()

    def _run(self):
        cevt = None # Control event
        while not cevt or len(self._Q)!=0:
            # Wait for first entry in queue
            if not cevt:
                cevt = self.waitn.Wait()

            # Wait a while to batch up messages
            try:
                if not cevt:
                    cevt = self.sleep.Wait(self._BT)
            except cothread.Timedout:
                pass

            self._Q, Q = [], self._Q
            self.waitn.Reset()

            #Q.sort(key=lambda E:E[1], reverse=True)

            if self._V:
                for dataevt in Q:
                    print dataevt
            if self._email:
                try:
                    self.email_events(Q)
                except:
                    print time.ctime(),'Failed to email',len(Q),'events'
                    traceback.print_exc()

            # Wait to enforce make rate
            try:
                if not cevt:
                    cevt = self.sleep.Wait(self._SP)
            except cothread.Timedout:
                pass

    def email_events(self, events):
        msg = MIMEMultipart()

        msg['To'] = self._conf.get('email.to')
        if not msg['To']:
            print 'No email recipients defined'
            return
        msg['From'] = self._conf.get('email.from', 'Alarm Mailer')
        msg['Subject'] = '%d Alarm Events'%len(events)

        ctxt = {'events':events, 'notifier':self._conf, 'now':time.ctime()}
        filename = self._conf.get('email.plain', 'template.txt')
        msg.attach(MIMEText(loader.render_to_string(filename, ctxt), 'plain'))
        filename = self._conf.get('email.html', 'template.html')
        msg.attach(MIMEText(loader.render_to_string(filename, ctxt), 'html'))

        if self._email_nosend:
            print 'Email Message'
            print msg.as_string()
            return # for debugging and template development

        HOST = self._conf.get('email.server', 'localhost')
        PORT = self._conf.get('email.port', 0)
        TO = map(str.strip, msg['To'])

        conn = smtplib.SMTP(HOST, PORT, None, 15)
        conn.sendmail(msg['From'], TO, msg.as_string())
        conn.quit()

    def render(self, events, ckey):
        filename = self._conf.get(ckey)
        return loader.render_to_string(filename, {'events':events})

def main():
    conf = sys.argv[1]
    P = ConfigParser()
    with open(conf,'r') as F:
        P.readfp(F)

    M = SectionProxy(P, 'main')

    notify = Notifier(SectionProxy(P, 'notifier'))

    groups = {}
    
    for pvg in map(str.strip, M.get('groups','').split(' ')):
        if not pvg:
            print 'No PV groups given'
            sys.exit(1)
        pvg = SectionProxy(P, pvg)
        if 'pvs' in pvg:
            pvlist = map(str.strip, pvg.get('pvs').split(' '))
        else:
            print 'No PV list specified for',pvg.name
            continue

        pvs = [AlarmPV(name, pvg, notify) for name in pvlist]

        groups[pvg.name] = pvs

    if len(groups)==0:
        print 'Empty configuration'
        sys.exit(1)

    print 'Starting'

    try:
        cothread.WaitForQuit()
    except KeyboardInterrupt:
        pass

    for pvs in groups.itervalues():
        for pv in pvs:
            pv.close()

    print 'Stopping'

    notify.close()

    print 'Done'

if __name__=='__main__':
    main()
