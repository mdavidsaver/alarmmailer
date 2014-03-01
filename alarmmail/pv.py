# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

from . import util

class NotifyFanout(object):
    def __init__(self):
        self._listeners = []
        self.add_notify = self._listeners.append
        self.del_notify = self._listeners.remove
    def add(self, evt):
        Qd = True
        for l in self._listeners:
            Qd &= l.add(evt)
        return Qd

class PV(object):
    def __init__(self, pvname, conf, notify):
        from cothread import catools as ca
        self._name, self._notify, self._conf = pvname, notify, conf
        self._prev = None
        self._sub = ca.camonitor(pvname, self._update,
                                 datatype=ca.DBR_STRING,
                                 format=ca.FORMAT_TIME,
                                 count=1,
                                 notify_disconnect=True)

    def close(self):
        self._sub.close()

    def _update(self, data):
        """Decide if an alarm is in effect and
        classify it
        """
        P, self._prev = self._prev, data

        if data.update_count!=1:
            self.notify.add(util.AlarmEvent(data, util.RES_LOST))

        reason = None
        if P is None:
            # Initial update
            if self._conf.oninitial:
                if not data.ok:
                    reason = util.RES_DISCONN
                if data.severity!=0:
                    reason = util.RES_ALARM
            return

        if data.ok:
            if P.severity and not data.severity:
                reason = util.RES_NORMAL
            elif not P.severity and data.severity:
                reason = util.RES_ALARM
            elif P.severity < data.severity:
                reason = util.RES_INCREASE
            elif P.severity > data.severity:
                reason = util.RES_DECREASE
        elif P.ok:
            reason = util.RES_DISCONN

        if reason is not None:
            evt = util.AlarmEvent(data, reason, self._conf)
            if not self._notify.add(evt):
                LOG.error('Lost: %s', evt)
            else:
                LOG.info('event: %s', evt)

class PrintNotify(object):
    def add(self, evt):
        print evt
        return True

if __name__=='__main__':
    logging.basicConfig(level=logging.DEBUG)
    from . import config
    import sys
    import cothread
    N = PrintNotify()
    C = config.PVNode(config.SectionProxy.fromArgs('testgrp', alarminitial='false',pvs='junk'))
    pvs = [PV(pv, C, N) for pv in sys.argv[1:]]
    N.add(util.InternalEvent(util.RES_START))
    try:
        cothread.WaitForQuit()
    except KeyboardInterrupt:
        pass
    print 'Done'
