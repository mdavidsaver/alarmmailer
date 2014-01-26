#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cothread
from cothread import cosocket

cosocket.socket_hook()

import time, sys, traceback, smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cothread import catools as ca

from ConfigParser import SafeConfigParser as ConfigParser, NoOptionError, NoSectionError

_SEVR = {0:'No Alarm', 1:'Minor', 2:'Major', 3:'Invalid', 4:'Disconnect'}
def SEVR(sevr):
    return _SEVR.get(sevr, 'Unknown')

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
        self._prev, self._isoos = None, False
        self._sub = ca.camonitor(pvname, self._update,
                                 format=ca.FORMAT_TIME,
                                 all_updates=True,
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
        if P is None:
            # Initial update
            if self._conf.getbool('alarminitial',False):
                if not data.ok:
                    self.alarm_not_conn(data)
                elif data.severity!=0:
                    self.alarm_increase(data)
            return

        RX = time.time()
        if data.ok:
            if abs(data.timestamp-RX)>50 and not self._isoos:
                self._isoos = True
                self.alarm_out_of_sync(data, RX)
            else:
                if self._isoos:
                    self.alarm_in_sync(data)
                self._isoos = False

            if P.severity and not data.severity:
                self.alarm_normal(data)
            elif P.severity < data.severity:
                self.alarm_increase(data)
            elif P.severity > data.severity:
                self.alarm_decrease(data)
        elif P.ok:
            self.alarm_not_conn(data)

    def alarm_not_conn(self, data):
        V = {'name':data.name, 'time':time.ctime(),
             'severity':'Disconnected', 'value':'???'}
        msg = self._conf.get('msg.disconnect', _dft_msg)
        self.notify.add(msg%V, (4,))

    def alarm_increase(self, data):
        V = {'name':data.name, 'time':time.ctime(data.timestamp),
             'severity':SEVR(data.severity), 'value':str(data)}
        msg = self._conf.get('msg.increase', _dft_msg)
        self.notify.add(msg%V, (data.severity,))

    def alarm_decrease(self, data):
        V = {'name':data.name, 'time':time.ctime(data.timestamp),
             'severity':SEVR(data.severity), 'value':str(data)}
        msg = self._conf.get('msg.decrease', _dft_msg)
        self.notify.add(msg%V, (data.severity,))

    def alarm_normal(self, data):
        V = {'name':data.name, 'time':time.ctime(data.timestamp),
             'severity':SEVR(data.severity), 'value':str(data)}
        msg = self._conf.get('msg.normal', _dft_msg)
        self.notify.add(msg%V, (0,))

    def alarm_out_of_sync(self, data, RX):
        V = {'name':data.name, 'time':time.ctime(data.timestamp),
             'severity':'Out of Sync', 'value':str(data)}
        msg = self._conf.get('msg.normal', _dft_msg)
        self.notify.add(msg%V, (3,))

    def alarm_in_sync(self, data, RX):
        V = {'name':data.name, 'time':time.ctime(data.timestamp),
             'severity':'Back in Sync', 'value':str(data)}
        msg = self._conf.get('msg.normal', _dft_msg)
        self.notify.add(msg%V, (0,))

class Notifier(object):
    _STOP = object()
    def __init__(self, conf):
        self._conf = conf
        self._V = conf.get('print',False)
        self._SP = conf.getdouble('maxperiod', 10.0)
        self._BT = conf.getdouble('holdoff', 3.0)
        self._N  = conf.getint('Qsize', 10)

        self._email = conf.getboolean('email', False)

        self._Q, self._oflow = [], False
        self.waitn = cothread.Event(auto_reset=False)
        self.sleep = cothread.Event(auto_reset=False)
        self.T = cothread.Spawn(self._run)

    def close(self):
        self.waitn.Signal(self._STOP)
        self.sleep.Signal(self._STOP)
        self.T.Wait()

    def add(self, msg, order):
        if len(self._Q)>self._N:
            if not self._oflow:
                self._oflow = True
                msg = 'Q overflow!!!!!!'
                order = (6,)
            else:
                return # Drop further events

        else:
            self._oflow = False

        self._Q.append((msg, order))
        self.waitn.Signal()

    def _run(self):
        evt = None
        while not evt or len(self._Q)!=0:
            # Wait for first entry in queue
            if not evt:
                evt = self.waitn.Wait()

            # Wait a while to batch up messages
            try:
                if not evt:
                    evt = self.sleep.Wait(self._BT)
            except cothread.Timedout:
                pass

            self._Q, Q = [], self._Q
            self.waitn.Reset()

            Q.sort(key=lambda E:E[1], reverse=True)

            if self._V:
                for msg, order in Q:
                    print order,msg
            if self._email:
                try:
                    self.email_events(Q)
                except:
                    print time.ctime(),'Failed to email',len(Q),'events'
                    traceback.print_exc()

            # Wait to enforce make rate
            try:
                if not evt:
                    evt = self.sleep.Wait(self._SP)
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

        msg.attach(self.format_plain(events))
        msg.attach(self.format_html(events))
        print 'Message'
        print msg.as_string()

        HOST = self._conf.get('email.server', 'localhost')
        PORT = self._conf.get('email.port', 0)
        TO = map(str.strip, msg['To'])

        conn = smtplib.SMTP(HOST, PORT, None, 15)
        conn.sendmail(msg['From'], TO, msg.as_string())
        conn.quit()

    def format_plain(self, events):
        msg = "Events:\n\n%s\n"%('\n'.join([M[0] for M in events]))
        return MIMEText(msg, 'plain')
    def format_html(self, events):
        msg = "<h3>Events</h3><ul>\n<li>%s</li>\n</ul>"%('</li>\n<li>'.join([M[0] for M in events]))
        return MIMEText(msg, 'html')

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

    notify.add("Starting at %s"%(time.ctime(),), (6,))

    try:
        cothread.WaitForQuit()
    except KeyboardInterrupt:
        pass

    for pvs in groups.itervalues():
        for pv in pvs:
            pv.close()

    notify.add("Stopping at %s"%(time.ctime(),), (6,))

    notify.close()

    print 'Done'

if __name__=='__main__':
    main()
