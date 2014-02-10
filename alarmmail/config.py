# -*- coding: utf-8 -*-
"""
Copyright 2014 Michael Davidsaver
GPL 2+
See license in README
"""

import logging
LOG = logging.getLogger(__name__)

import os, os.path, itertools

from ConfigParser import SafeConfigParser as ConfigParser, NoOptionError, NoSectionError

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

    @classmethod
    def fromArgs(cls, name, **kws):
        """Build a section from provided keyword arguments.
        For testing
        """
        P = ConfigParser()
        P.add_section(name)
        for k,v in kws.iteritems():
            P.set(name, k, v)
        return cls(P, name)

class PVNode(object):
    def __init__(self, C):
        self.name = C.name
        if 'pvs' in C:
            pvlist = map(str.strip, C.get('pvs').split(' '))
            desclist = pvlist
        elif 'pvlist_file' in C:
            # pv list from file, one PV per line.  Blanks and comments ignored
            filename = os.path.join(os.getcwd(), C.get('pvlist_file'))
            LOG.debug('Reading PV list file: %s',filename)
            with open(filename,'r') as FP:
                pvlist, desclist = [], []
                for line in map(str.lstrip, FP.readlines()):
                    # filter out blank lines and comments
                    if not line or line[0]=='#':
                        continue
                    parts = map(str.strip, line.split('|',1))
                    pvlist.append(parts[0])
                    if len(parts)>1:
                        desclist.append(parts[1])
                    else:
                        desclist.append(parts[0])
                    
        else:
            raise ValueError("No PV list found for group %s"%C.name)

        if not pvlist:
            raise ValueError("Empty PV list for group %s"%C.name)

        self.pvs = pvlist
        self.desc = dict([(p,d) for p,d in itertools.izip(iter(pvlist), iter(desclist))])
        self.oninitial = C.getbool('alarminitial',False)

class DestNode(object):
    def __init__(self, C):
        self.name = C.name
        self.mto = C.get('to','').split(',')
        self.mfrom = C.get('from', '"Alarm Mailer" <mailer@localhost>')
        self.msubject = C.get('subject', '%(cnt)d Alarm Events')

        self.delay = C.getdouble('delay', 300.0)
        self.holdoff = C.getdouble('holdoff', 600.0)
        self.qsize = C.getint('queueSize', 200)

        self.groups = C.get('groups','').split(' ')

        self.plain = C.get('plain', 'template.txt')
        self.html = C.get('html', 'template.html')
        
        self.oninitial = C.getbool('sendinitial',False)

        if not self.groups or self.groups==['']:
            raise ValueError('No PV groups specified for destination %s'%C.name)

        elif not self.mto or self.mto==['']:
            raise ValueError('Destination %s has not recipient (to) list'%C.name)

def loadconfig(cfile):
    main = ConfigParser()
    with open(cfile,'r') as FP:
        main.readfp(FP)
    if not main.has_section('main'):
        raise ValueError('%s: missing [main]'%cfile)
    MS = SectionProxy(main, 'main')

    pvconf, destconf = ConfigParser(), ConfigParser()
    with open(MS.get('pvfile','pvs.conf'), 'r') as FP:
        pvconf.readfp(FP)
    with open(MS.get('destfile','dest.conf'), 'r') as FP:
        destconf.readfp(FP)

    pvnodes, destnodes = [], []
    
    pvnodes = dict([(S,PVNode(SectionProxy(pvconf,S))) for S in pvconf.sections()])
    destnodes = dict([(S,DestNode(SectionProxy(destconf,S))) for S in destconf.sections()])

    if not pvnodes:
        raise ValueError("No PV groups")
    if not destnodes:
        raise ValueError("No destinations")

    for dest in destnodes.itervalues():
        for G in dest.groups:
            if G not in pvnodes:
                raise ValueError('Destination %s references PV group %s which does not exist'%(dest.name,G))

    return {"main":MS,
            "mail":SectionProxy(main,'mail'),
            "pv":pvnodes,
            "dest":destnodes}

if __name__=='__main__':
    import sys
    print loadconfig(sys.argv[1])
