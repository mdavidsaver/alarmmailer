# EPICS Alarm Mailer

The Alarm Mailer is a daemon which monitors lists of PVs for alarms.
Logs of alarms are send to pre-configured lists of recipients.

Requirements:

* Python - >=2.7, <3.0
* Django - >=1.2
* cothread - >=2.12

Configuration is in three files.  The main file (eg. mailer.conf)
references the other two (eg. dest.conf and pvs.conf) which
contain lists of recipients and pvs respectively.

A small working test IOC and examples are present in test/

## Configuration

Configuration of the alarmmailer daemon is done in three files:
[mailer.conf](mailer.conf), [pvs.conf](pvs.conf), and [dest.conf](dest.conf).

The file [mailer.conf](mailer.conf) contains global configuration, mainly related to the mail server.
This is where the SMTP server host name or IP address is given.
It also features configuration for the SMTP server send queue.
The default configuration is to accumulate mails for 30 second before sending.

As the name suggests [pvs.conf](pvs.conf) is where Process Variables groups are specified.
Each section of the file defines one group.
The PV list can be given as part of the file, with a **pvs=pv1 pv2 ...** line,
or in a separate text file referenced with **pvs_list=list.pvs**.

A PV list file gives one PV per line, and may optionally include a user friendly string
to be used in place of the PV name.

    pv:one:rbv
    pv:two:rbv | Device two is broken
    pv:three:rbv | Device three has a problem

Each section of the [dest.conf](dest.conf) file defines one email destination.
This takes a **to=myaddr@xyz.invalid another@xyz.invalid**
and a list of PV group names **groups=grp1 grp2**.

It may also change the alarm event receive queue.
By default alarms are accumulated for 5 minutes before sending a first email.
After the first email alarms are accumulated for 15 minutes before sending
further emails.
If no mail is sent for more than 15 minutes, then delay restarts to the original 5 minutes.

Up to 300 alarm events will be buffered per destination.
Further alarms are dropped.

## Templates

Alarm notification email is formatted as multi-part MIME with both plain text and HTML versions.
There is a separate template file for each: template.txt and template.html.
Template expansion uses the [Django template engine](https://docs.djangoproject.com/en/1.7/)

The default templates group alarm events from each PV list,
and sort them in increasing time order.

## Debian

On Debian Linux systems the alarmmailer installs configuration in */etc/alarmmailer/*
and places logs in */var/log/alarmmailer/*.
A SysV style init script is included which includes the additional command **check**
to perform some verify of configuration.

## Testing

The alarmmailer executable understands three sub-commands: daemon, mailtest, and expandtest.

**mailtest** is intended to check SMTP server configuration.
The following sends a test email.

    $ alarmmailer -C mailer.conf mailtest --to "me@somewhere.invalid another@xyz.invalid"

**expandtest** is useful when making changes to the provided Django templates.
The following expands a template file using a static set of alarm events.

    $ alarmmailer -C mailer.conf expandtest template.txt

If the *[mail]* section of [mailer.conf](mailer.conf) contains **nosend=True**
then emails are not sent, but instead printed to the log.

## Copying

Copyright 2014 Michael Davidsaver <mdavidsaver@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
