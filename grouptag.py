#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2015-2016 Mathieu Dugas <mad2k6@nabb.ca>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:

# - Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of the Mumble Developers nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# `AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#
# grouptag.py
#
# Module for moving/muting/deafening idle players after
# a certain amount of time and unmuting/undeafening them
# once they become active again
#

from mumo_module import (commaSeperatedIntegers,
                         commaSeperatedStrings,
                         MumoModule)

from threading import Timer
import re




class grouptag(MumoModule):
    default_config = {'grouptag':(
                             ('interval', int, 10),
                             ('servers', commaSeperatedIntegers, []),
                             ),
                      lambda x: re.match('(all)|(server_\d+)', x):(
                             ('groupmap', commaSeperatedStrings, ['admin:admin']),
                             ),
                    }
    
    def __init__(self, name, manager, configuration=None):
        MumoModule.__init__(self, name, manager, configuration)
        self.murmur = manager.getMurmurModule()
        self.watchdog = None

    def connected(self):
        self.affectedusers = {} # {serverid:set(sessionids,...)}

        manager = self.manager()
        log = self.log()
        log.debug("Register for Meta & Server callbacks")
        
        cfg = self.cfg()
        servers = cfg.grouptag.servers
        if not servers:
            servers = manager.SERVERS_ALL

        manager.subscribeServerCallbacks(self, servers)
        manager.subscribeMetaCallbacks(self, servers)
        
        if not self.watchdog:
            self.watchdog = Timer(cfg.grouptag.interval, self.setTag)
            self.watchdog.start()
    
    def disconnected(self):
        self.affectedusers = {}
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None

    def isuseringroup(self, server, user, group_to_check):
        '''Checks if userid is member of the excluded_for_afk group in the root channel'''
        try:
            scfg = getattr(self.cfg(), 'server_%d' % int(server.id()))
        except AttributeError:
            scfg = self.cfg().all

        ACL = server.getACL(0)

        userid = user.userid

        for group in ACL[1]:
            if userid in group.members and group.name == group_to_check:
                return True
        return False

    def setTag(self):
        cfg = self.cfg()
        try:
            meta = self.manager().getMeta()

            if not cfg.grouptag.servers:
                servers = meta.getBootedServers()
            else:
                servers = [meta.getServer(server) for server in cfg.grouptag.servers]

            for server in servers:
                if not server: continue

                if server:
                    for user in server.getUsers().itervalues():
                            self.updateTags(server, user)
        finally:
            # Renew the timer
            self.watchdog = Timer(cfg.grouptag.interval, self.setTag)
            self.watchdog.start()
                        
    def updateTags(self, server, user):
        log = self.log()
        sid = server.id()

        try:
            scfg = getattr(self.cfg(), 'server_%d' % sid)
        except AttributeError:
            scfg = self.cfg().all

        try:
            index = self.affectedusers[sid]
        except KeyError:
            self.affectedusers[sid] = set()
            index = self.affectedusers[sid]

        # Remember values so we can see changes later

        tags = []

        # grab all the appropriate tags for the user and update the tagset.
        for i in range(len(scfg.groupmap) - 1, -1, -1):
            try:
                map = scfg.groupmap[i]
            except IndexError:
                log.warning("Incomplete configuration for stage %d of server %i, ignored", i, server.id())
                continue

            group = map.split(':')[0]
            tag = map.split(':')[1]

            if self.isuseringroup(server, user, group) and tag not in tags:
                log.info('Adding tag %s to user %s on serverid %i', tag, user.name, server.id())
                tags.append(tag)

        userstate = server.getState(int(user.session))

        if user.name.find('[') > 0:
            original_username = user.name[0:user.name.find('[') -1]
        else:
            original_username = user.name

        if len(tags) > 0:
            userstate.name='%s [ %s ]' % (original_username, ', '.join(tags))
        else:
            userstate.name='%s' % (original_username)

        server.setState(userstate)
        log.info('Setting tags %s to user %s on server %d', tags, user.name, server.id())
    #
    #--- Server callback functions
    #
    def userDisconnected(self, server, state, context=None):
        try:
            index = self.affectedusers[server.id()]
            if state.session in index:
                index.remove(state.session)
        except KeyError:
            pass

    def userConnected(self, server, state, context=None):
        self.setTag();

    def userStateChanged(self, server, state, context=None): pass
    def userTextMessage(self, server, user, message, current=None): pass
    def channelCreated(self, server, state, context=None): pass
    def channelRemoved(self, server, state, context=None): pass
    def channelStateChanged(self, server, state, context=None): pass

    #
    #--- Meta callback functions
    #
    
    def started(self, server, context = None):
        sid = server.id()
        self.affectedusers[sid] = set()
        self.log().debug('Handling server %d', sid)
    
    def stopped(self, server, context = None):
        sid = server.id()
        self.affectedusers[sid] = set()
        self.log().debug('Server %d gone', sid)
    