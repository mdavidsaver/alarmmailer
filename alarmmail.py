#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A daemon which monitors one or more groups of Process Variables
and sends email periodic email with a list alarms which occur.
"""

import time, sys, os, os.path, atexit
from optparse import  OptionParser

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ConfigParser import SafeConfigParser as ConfigParser, NoOptionError, NoSectionError

import logging
LOG = logging.getLogger(__name__)

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
        self.name = reason.message
        self.value = ''
        self.sevr = 5
        self.severity = "Internal"
        self.status = 0
        self.timestamp = self.rxtimestamp = time.time()
        self.time = self.rxtime = time.ctime(self.timestamp)

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
RES_START = AlarmReason(7, "Mailer starting")

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
        from cothread import catools as ca
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
        P, self._prev = self._prev, data

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
        import cothread
        self._conf = conf
        self._V = conf.get('print',False)
        self._SP = conf.getdouble('maxperiod', 600.0)
        self._BT = conf.getdouble('holdoff', 300.0)
        self._N  = conf.getint('Qsize', 200)

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
        import cothread
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

            if self._V:
                for dataevt in Q:
                    LOG.debug('Event: %s',dataevt)
            if self._email:
                LOG.info('Sending alarm email with %d events', len(Q))
                try:
                    self.email_events(Q)
                except:
                    LOG.exception("Failed to email %d events",len(Q))

            # Wait to enforce make rate
            # The max. period is actually the sum _BT + _SP
            try:
                if not cevt:
                    cevt = self.sleep.Wait(self._SP)
            except cothread.Timedout:
                pass

    def email_events(self, events):
        import smtplib
        import django.template.loader as loader
        msg = MIMEMultipart()

        # take mail header directly from configuration
        msg['To'] = self._conf.get('email.to')
        if not msg['To']:
            LOG.warn('No email recipients defined')
            return
        msg['From'] = self._conf.get('email.from', 'Alarm Mailer')
        msg['Subject'] = '%d Alarm Events'%len(events)

        # the template context.
        ctxt = {'events':events, 'notifier':self._conf, 'now':time.ctime()}
        # render to text for both mime types
        filename = self._conf.get('email.plain', 'template.txt')
        msg.attach(MIMEText(loader.render_to_string(filename, ctxt), 'plain'))
        filename = self._conf.get('email.html', 'template.html')
        msg.attach(MIMEText(loader.render_to_string(filename, ctxt), 'html'))

        if self._email_nosend:
            LOG.debug('Email Message')
            LOG.debug(msg.as_string())
            return # for debugging and template development

        HOST = self._conf.get('email.server', 'localhost')
        PORT = self._conf.get('email.port', 0)
        TO = map(str.strip, msg['To'])

        conn = smtplib.SMTP(HOST, PORT, None, 15)
        conn.sendmail(msg['From'], TO, msg.as_string())
        conn.quit()

_FMT = "%(asctime)s %(levelname)s:%(message)s"

class main(object):
    def __init__(self):
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
    
        self.opts, args = parser.parse_args()
    
        P = ConfigParser()
        with open(self.opts.config,'r') as F:
            P.readfp(F)
        self.P = P

    def daemonize(self):
        """Fun double fork to free the daemon process
        of its parent.
        """
        # A pipe to allow the parent to wait until the child
        # has successfully initialized (or not).
        RD, WR = os.pipe()
        c1pid = os.fork()
        if c1pid > 0:
            # original process
            os.close(WR)
            RD = os.fdopen(RD, 'r')
            print 'Waiting for daemon to initialize',c1pid
            msg = '127'
            for msg in RD.readlines():
                print msg,
            RD.close()
            ret = int(msg)
            if ret:
                print 'Daemon failed to start.',ret
            else:
                print 'Daemon started'
            sys.exit(ret)

        # first child
        os.close(RD)

        os.chdir('/')
        os.setsid()
        os.umask(0)

        c2pid = os.fork()
        if c2pid > 0:
            os.close(WR)
            sys.exit(0) # end first child

        WR = os.fdopen(WR, 'w')

        # Initialize logging before detaching stdin/out
        from logging.handlers import RotatingFileHandler
        root = logging.getLogger()
        fmt = logging.Formatter(_FMT)
        handler = RotatingFileHandler(self.opts.log, maxBytes=100000, backupCount=5)
        handler.setFormatter(fmt)
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        WR.write("Logging initialized\n")

        sys.stdout.flush()
        sys.stderr.flush()
        #TODO: Don't leak descriptors...
        os.dup2(os.open(os.path.devnull, os.O_RDONLY), sys.stdin.fileno())
        os.dup2(os.open(os.path.devnull, os.O_WRONLY), sys.stdout.fileno())
        os.dup2(os.open(os.path.devnull, os.O_WRONLY), sys.stderr.fileno())
        WR.write("Output redirected\n")

        try:
            atexit.register(os.unlink, self.opts.pid)
            FD = os.open(self.opts.pid, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0644)
            os.write(FD, "%d"%os.getpid())
            os.close(FD)
        except:
            WR.write("Failed to create pid file %s\n"%self.opts.pid)
            import traceback
            traceback.print_exc(file=WR)
            WR.write("1\n")
            sys.exit(1)
        # At this point we know we have exclusive control of the log
        LOG.info("PID file written")

        return WR
        # second child

    def start(self):
        import cothread
        if self.opts.daemonize:
            WR = self.daemonize()
        else:
            logging.basicConfig(level=logging.DEBUG, format=_FMT)

        from cothread import cosocket
        cosocket.socket_hook()

        try:
            LOG.info("Daemon startting")
            self.startChild()
            LOG.info("Daemon running")
        except:
            if self.opts.daemonize:
                WR.write("1\n")
            raise
        else:
            if self.opts.daemonize:
                import signal
                def handler(sig,frame):
                    import cothread
                    cothread.Quit()
                signal.signal(signal.SIGHUP, handler)
                signal.signal(signal.SIGINT, handler)
                signal.signal(signal.SIGTERM, handler)
                # notify original parent that we have successfully started
                WR.write("0\n")
                WR.close()

        try:
            cothread.WaitForQuit()
        except KeyboardInterrupt:
            pass
    
        LOG.info("Shutting down")
    
        for pvs in self.groups.itervalues():
            for pv in pvs:
                pv.close()
        
        self.notify.close()
    
        LOG.info("Shut down complete")

    def startChild(self):
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            from django.conf import settings
            settings.configure(INSTALLED_APPS=[], TEMPLATE_DIRS=[self.opts.template], TEMPLATE_DEBUG=True)

        P = self.P
        M = SectionProxy(P, 'main')

        self.notify = notify = Notifier(SectionProxy(P, 'notifier'))
    
        self.groups = groups = {}
        
        for pvg in map(str.strip, M.get('groups','').split(' ')):
            if not pvg:
                LOG.fatal('No PV groups given')
                sys.exit(1)
            pvg = SectionProxy(P, pvg)
            if 'pvs' in pvg:
                # space seperated pv list from config file
                pvlist = map(str.strip, pvg.get('pvs').split(' '))

            elif 'pvlist_file' in pvg:
                # pv list from file, one PV per line.  Blanks and comments ignored
                filename = pvg.get('pvlist_file')
                LOG.debug('Reading PV list file: %s',filename)
                with open(filename,'r') as FP:
                    pvlist = [line.strip() for line in FP.readlines()]
                    # filter out blank lines and comments
                    pvlist = filter(lambda line:line and line[0]!='#', pvlist)

            else:
                LOG.warn('No PV list specified for group %s',pvg.name)
                continue
    
            groups[pvg.name] = [AlarmPV(name, pvg, notify) for name in pvlist]
    
        if len(groups)==0:
            LOG.fatal('Empty configuration')
            sys.exit(1)

        if M.get('alarminitial', False):
            self.notify.add(InternalEvent(RES_START))

if __name__=='__main__':
    M = main()
    try:
        M.start()
    except (SystemExit, KeyboardInterrupt):
        raise
    except:
        LOG.exception("Unhandled exception")
        raise
    else:
        LOG.info('Done')
