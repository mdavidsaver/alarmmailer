# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import time

_SEVR = {0:'No Alarm', 1:'Minor   ', 2:'Major   ', 3:'Invalid ', 4:'Disconn.'}
def SEVR(sevr):
    return _SEVR.get(sevr, 'Unknown')

class DummyValue(object):
    ok = False
    value = None
    timestamp = 0
    status = 0
    severity = 4
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return "N/A"

class AlarmEvent(object):
    def __init__(self, data, meta, reason, conf):
        assert data is not None
        self._data, self._meta, self.reason, self.conf = data, meta, reason, conf
        self.rxtimestamp = time.time()
        if not data.ok:
            data.severity = 4
            data.status = 0
            data.timestamp = self.rxtimestamp
    def __getattr__(self, key):
        try:
            return getattr(self._data, key)
        except AttributeError:
            return getattr(self._meta, key)
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
    @property
    def units(self):
        try:
            return self._meta.units
        except:
            return ''
    @property
    def desc(self):
        return self.conf.desc.get(self._data.name, self._data.name)
    def __repr__(self):
        return 'AlarmEvent(\'%s\', %s, %s, %s)'%(self._data.name, self._data, self.severity, self.reason)

class InternalEvent(object):
    def __init__(self, reason):
        self.reason = reason
        self.name = reason.message
        self.value = ''
        self.sevr = 5
        self.severity = "Internal"
        self.status = 0
        self.timestamp = self.rxtimestamp = time.time()
        self.time = self.rxtime = time.ctime(self.timestamp)
    def __repr__(self):
        return 'InternalEvent(%s)'%(self.reason)

class AlarmReason(object):
    def __init__(self, code, msg):
        self.code, self.message = code, msg
    def __str__(self):
        return '%s (%d)'%(self.message, self.code)
    def __repr__(self):
        return 'AlarmReason(%d, "%s")'%(self.code, self.message)
RES_NORMAL = AlarmReason(0, "Alarm cleared")
RES_ALARM = AlarmReason(1, "Alarm")
RES_INCREASE = AlarmReason(2, "Severity increased")
RES_DECREASE = AlarmReason(3, "Severity decreased")
RES_DISCONN = AlarmReason(4, "Connection lost")
RES_QFULL = AlarmReason(5, "Queue full")
RES_LOST = AlarmReason(6, "Lost Events")
RES_START = AlarmReason(7, "Mailer starting")

class WorkerQueue(object):
    _STOP = object()
    def __init__(self, action=None, delay=1.0, holdoff=5.0, qsize=10):
        import cothread
        holdoff -= delay
        if holdoff <0.0:
            holdoff = 0.0
        self.delay, self.holdoff, self.qsize = delay, holdoff, qsize
        self._Q, self.overflow, self._Qlim = [], False, qsize
        self.waitn = cothread.Event(auto_reset=False)
        self.sleep = cothread.Event(auto_reset=False)
        self.T = cothread.Spawn(self._run)
        if action:
            self.process = action

    def close(self):
        self.waitn.Signal(self._STOP)
        self.sleep.Signal(self._STOP)
        self.T.Wait()

    def add(self, evt):
        if len(self._Q)>self.qsize:
            if not self.overflow:
                self.overflow = True
                LOG.debug("%s queue overflow", self)
            return False # Drop further events

        else:
            self.overflow = False

        self._Q.append(evt)
        self.waitn.Signal()
        return True

    def process(self, Q, overflow):
        LOG.error("Ignoring %s (%s)",Q,overflow)

    def _run(self):
        import cothread
        cevt = None # Control event
        while not cevt or len(self._Q)!=0:
            # Wait for first entry in queue
            if not cevt:
                cevt = self.waitn.Wait()

            # Wait a while to batch up messages
            try:
                if not cevt:
                    cevt = self.sleep.Wait(self.delay)
            except cothread.Timedout:
                pass

            self._Q, Q = [], self._Q
            self.waitn.Reset()

            if not Q:
                continue

            try:
                self.process(Q, self.overflow)
            except:
                LOG.exception("%s Failed to process %d events",self,len(Q))

            # Wait to enforce make rate
            # The max. period is actually the sum _BT + _SP
            try:
                if not cevt:
                    cevt = self.sleep.Wait(self.holdoff)
            except cothread.Timedout:
                pass

if __name__=='__main__':
    import cothread
    def action(Q,of):
        print '<<',Q,of
    W = WorkerQueue(action)
    for n in range(30):
        print '>>',n
        W.add(('event',n))
        if n < 20:
            cothread.Sleep(1)
        else:
            cothread.Sleep(0.1)
    print 'Closing'
    W.close()
    print 'Done'
