#!/usr/bin/python

from distutils.core import setup

setup(
  name='alarmmailer',
  version='1.0-dev',
  description='Email alarm notifier for EPICS',
  author = 'Michael Davidsaver',
  author_email = 'mdavidsaver@gmail.com',
  license = 'GPL2',
  url = 'http://github.com/mdavidsaver/alarmmailer',
  
  packages = ['alarmmail', 'alarmmail.templatetags'],
  scripts = ['alarmmailer'],
  data_files = [
    ('/etc/alarmmailer', ['mailer.conf', 'pvs.conf', 'dest.conf',
                          'template.txt', 'template.html']),
  ]
)
