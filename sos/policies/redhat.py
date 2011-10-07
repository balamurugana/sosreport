## Implement policies required for the sos system support tool

## Copyright (C) Steve Conklin <sconklin@redhat.com>

### This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

# This enables the use of with syntax in python 2.5 (e.g. jython)
from __future__ import with_statement

import os
import sys
from tempfile import gettempdir
import random
import re
import platform
import time
from subprocess import Popen, PIPE, call
from collections import deque

try:
    from hashlib import md5
except ImportError:
    from md5 import md5

from sos import _sos as _
from sos.plugins import RedHatPlugin, IndependentPlugin
from sos.policies import Policy, PackageManager

sys.path.insert(0, "/usr/share/rhn/")
try:
    from up2date_client import up2dateAuth
    from up2date_client import config
    from rhn import rpclib
except:
    # might fail if non-RHEL
    pass


class RHELPackageManager(PackageManager):

    def _get_rpm_list(self):
        pkg_list = subprocess.Popen(["rpm", "-qa", "--queryformat", "%{NAME}|%{VERSION}\\n"],
            stdout=subprocess.PIPE).communicate()[0].splitlines()
        self._rpms = {}
        for pkg in pkg_list:
            name, version = pkg.split("|")
            self._rpms[name] = {
                    'name': name,
                    'version': version
                    }

    def allPkgsByName(self, name):
        return fnmatch.filter(self.allPkgs().keys(), name)

    def allPkgsByNameRegex(self, regex_name, flags=None):
        reg = re.compile(regex_name, flags)
        return [pkg for pkg in self.allPkgs().keys() if reg.match(pkg)]

    def pkgByName(self, name):
        try:
            self.AllPkgsByName(name)[-1]
        except Exception:
            return None

    def allPkgs(self):
        if not self._rpms:
            self._rpms = self._get_rpm_list()
        return self._rpms

    def pkgNVRA(self, pkg):
        fields = pkg.split("-")
        version, release, arch = fields[-3:]
        name = "-".join(fields[:-3])
        return (name, version, release, arch)


class RHELPolicy(Policy):

    def __init__(self):
        self.report_file = ""
        self.report_file_ext = ""
        self.report_md5 = ""
        self.reportName = ""
        self.ticketNumber = ""
        self._parse_uname()
        self.package_manager = RHELPackageManager()

    def setCommons(self, commons):
        self.cInfo = commons

    def validatePlugin(self, plugin_class):
        "Checks that the plugin will execute given the environment"
        return issubclass(plugin_class, RedHatPlugin) or issubclass(plugin_class, IndependentPlugin)

    def check(self):
        "This method checks to see if we are running on RHEL. It returns True or False."
        return os.path.isfile('/etc/redhat-release')

    def preferedArchive(self):
        from sos.utilities import TarFileArchive
        return TarFileArchive

    def pkgByName(self, name):
        return self.package_manager.pkgByName(name)

    def _parse_uname(self):
        (system, node, release,
         version, machine, processor) = platform.uname()
        self.hostname = node
        self.release = release
        self.smp = version.split()[1] == "SMP"
        self.machine = machine

    def _system(self, cmd):
        p = Popen(cmd,
                  shell=True,
                  stdout=PIPE,
                  stderr=PIPE,
                  bufsize=-1)
        stdout, stderr = p.communicate()
        status = p.returncode
        return stdout, stderr, status

    def runlevelByService(self, name):
        ret = []
        out, err, sts = self._system("LC_ALL=C /sbin/chkconfig --list %s" % name)
        if err:
            return ret
        for tabs in out.split()[1:]:
            try:
                (runlevel, onoff) = tabs.split(":", 1)
            except:
                pass
            else:
                if onoff == "on":
                    ret.append(int(runlevel))
        return ret

    def runlevelDefault(self):
        try:
            with open("/etc/inittab") as fp:
                pattern = r"id:(\d{1}):initdefault:"
                text = fp.read()
                return int(re.findall(pattern, text)[0])
        except:
            return 3

    def kernelVersion(self):
        return self.release

    def hostName(self):
        return self.hostname

    def rhelVersion(self):
        try:
            pkg = self.pkgByName("redhat-release") or \
            self.allPkgsByNameRegex("redhat-release-.*")[-1]
            pkgname = pkg["version"]
            if pkgname[0] == "4":
                return 4
            elif pkgname in [ "5Server", "5Client" ]:
                return 5
            elif pkgname[0] == "6":
                return 6
        except:
            pass
        return False

    def rhnUsername(self):
        try:
            cfg = config.initUp2dateConfig()

            return rpclib.xmlrpclib.loads(up2dateAuth.getSystemId())[0][0]['username']
        except:
            # ignore any exception and return an empty username
            return ""

    def isKernelSMP(self):
        return self.smp

    def getArch(self):
        return self.machine

    def preWork(self):
        # this method will be called before the gathering begins

        localname = self.rhnUsername()
        if len(localname) == 0: localname = self.hostName()

        if not self.cInfo['cmdlineopts'].batch:
            try:
                self.reportName = raw_input(_("Please enter your first initial and last name [%s]: ") % localname)
                self.reportName = re.sub(r"[^a-zA-Z.0-9]", "", self.reportName)

                self.ticketNumber = raw_input(_("Please enter the case number that you are generating this report for: "))
                self.ticketNumber = re.sub(r"[^0-9]", "", self.ticketNumber)
                print
            except:
                print
                sys.exit(0)

        if len(self.reportName) == 0:
            self.reportName = localname

        if self.cInfo['cmdlineopts'].customerName:
            self.reportName = self.cInfo['cmdlineopts'].customerName
            self.reportName = re.sub(r"[^a-zA-Z.0-9]", "", self.reportName)

        if self.cInfo['cmdlineopts'].ticketNumber:
            self.ticketNumber = self.cInfo['cmdlineopts'].ticketNumber
            self.ticketNumber = re.sub(r"[^0-9]", "", self.ticketNumber)

        return

    def packageResults(self, archive_filename):
        print _("Creating compressed archive...")
        self.report_file = archive_filename
        # actually compress the archive if necessary

    def getArchiveName(self):
        if len(self.ticketNumber):
            self.reportName = self.reportName + "." + self.ticketNumber
        else:
            self.reportName = self.reportName

        return "sosreport-%s-%s" % (self.reportName, time.strftime("%Y%m%d%H%M%S"))

    def encryptResults(self):
        # make sure a report exists
        if not self.report_file:
           return False

        print _("Encrypting archive...")
        gpgname = self.report_file + ".gpg"

        try:
           keyring = self.cInfo['config'].get("general", "gpg_keyring")
        except:
           keyring = "/usr/share/sos/rhsupport.pub"

        try:
           recipient = self.cInfo['config'].get("general", "gpg_recipient")
        except:
           recipient = "support@redhat.com"

        p = Popen("""/usr/bin/gpg --trust-model always --batch --keyring "%s" --no-default-keyring --compress-level 0 --encrypt --recipient "%s" --output "%s" "%s" """ % (keyring, recipient, gpgname, self.report_file),
                    shell=True, stdout=PIPE, stderr=PIPE, bufsize=-1)
        stdout, stderr = p.communicate()
        if p.returncode == 0:
            os.unlink(self.report_file)
            self.report_file = gpgname
        else:
           print _("There was a problem encrypting your report.")
           sys.exit(1)

    def displayResults(self, final_filename=None):

        self.report_file = final_filename

        # make sure a report exists
        if not self.report_file:
           return False

        # calculate md5
        fp = open(self.report_file, "r")
        self.report_md5 = md5(fp.read()).hexdigest()
        fp.close()

        # store md5 into file
        fp = open(self.report_file + ".md5", "w")
        fp.write(self.report_md5 + "\n")
        fp.close()

        print
        print _("Your sosreport has been generated and saved in:\n  %s") % self.report_file
        print
        if len(self.report_md5):
            print _("The md5sum is: ") + self.report_md5
            print
        print _("Please send this file to your support representative.")
        print

    def uploadResults(self):

        self.report_file = final_filename

        # make sure a report exists
        if not self.report_file:
            return False

        print
        # make sure it's readable
        try:
            fp = open(self.report_file, "r")
        except:
            return False

        # read ftp URL from configuration
        if self.cInfo['cmdlineopts'].upload:
            upload_url = self.cInfo['cmdlineopts'].upload
        else:
            try:
               upload_url = self.cInfo['config'].get("general", "ftp_upload_url")
            except:
               print _("No URL defined in config file.")
               return

        from urlparse import urlparse
        url = urlparse(upload_url)

        if url[0] != "ftp":
            print _("Cannot upload to specified URL.")
            return

        # extract username and password from URL, if present
        if url[1].find("@") > 0:
            username, host = url[1].split("@", 1)
            if username.find(":") > 0:
                username, passwd = username.split(":", 1)
            else:
                passwd = None
        else:
            username, passwd, host = None, None, url[1]

        # extract port, if present
        if host.find(":") > 0:
            host, port = host.split(":", 1)
            port = int(port)
        else:
            port = 21

        path = url[2]

        try:
            from ftplib import FTP
            upload_name = os.path.basename(self.report_file)

            ftp = FTP()
            ftp.connect(host, port)
            if username and passwd:
                ftp.login(username, passwd)
            else:
                ftp.login()
            ftp.cwd(path)
            ftp.set_pasv(True)
            ftp.storbinary('STOR %s' % upload_name, fp)
            ftp.quit()
        except:
            print _("There was a problem uploading your report to Red Hat support.")
        else:
            print _("Your report was successfully uploaded to %s with name:" % (upload_url,))
            print "  " + upload_name
            print
            print _("Please communicate this name to your support representative.")
            print

        fp.close()

# vim: ts=4 sw=4 et