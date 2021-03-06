#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# HFOS - Hackerfleet Operating System
# ===================================
# Copyright (C) 2011-2019 Heiko 'riot' Weinen <riot@c-base.org> and others.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = "Heiko 'riot' Weinen"
__license__ = "AGPLv3"

"""


Module: Chat
============

Chat manager


"""

from isomer.robot.events import control_update

from isomer.component import ConfigurableComponent, authorized_event, handler
from isomer.events.client import send
from isomer.logger import warn, critical


# Remote Control events

class control_request(authorized_event):
    """A client wants to remote control a servo"""


class control_release(authorized_event):
    """A client wants to remote control a servo"""


class data(authorized_event):
    """A client wants to remote control a servo"""


class RemoteControlManager(ConfigurableComponent):
    """
    Robotics remote control manager

    Handles
    * authority of controlling clients
    * incoming remote control messages
    """

    configprops = {}
    channel = 'isomer-web'

    def __init__(self, *args):
        super(RemoteControlManager, self).__init__("RCM", *args)

        self.remote_controller = None

        self.log("Started")

    def clientdisconnect(self, event):
        """Handler to deal with a possibly disconnected remote controlling
        client
        :param event: ClientDisconnect Event
        """

        try:
            if event.clientuuid == self.remote_controller:
                self.log("Remote controller disconnected!", lvl=critical)
                self.remote_controller = None
        except Exception as e:
            self.log("Strange thing while client disconnected", e, type(e))

    @handler(control_request)
    def control_request(self, event):
        username = event.user.account.name
        client_name = event.client.name
        client_uuid = event.client.uuid

        self.log("Client wants to remote control: ", username,
                 client_name, lvl=warn)
        if not self.remote_controller:
            self.log("Success!")
            self.remote_controller = client_uuid
            self.fireEvent(send(client_uuid, {
                'component': 'isomer.robot.rcmanager',
                'action': 'control_request',
                'data': True
            }))
        else:
            self.log("No, we're already being remote controlled!")
            self.fireEvent(send(client_uuid, {
                'component': 'isomer.robot.rcmanager',
                'action': 'control_request',
                'data': False
            }))

        return

    @handler(control_release)
    def control_release(self, event):
        username = event.user.account.name
        client_name = event.client.name
        client_uuid = event.client.uuid

        if self.remote_controller == event.client.uuid:
            self.log("Client leaves control!", username, client_name,
                     lvl=warn)
            # TODO: Switch to a possible fallback controller
            self.remote_controller = None
            self.fireEvent(send(client_uuid, {
                'component': 'isomer.robot.rcmanager',
                'action': 'control_release',
                'data': True
            }))
        return

    @handler(data)
    def data(self, event):
        control_data = event.data

        self.log("Control data received: ", control_data)
        if event.client.uuid == self.remote_controller:
            self.log("Valid data, handing on to machineroom.")

            self.fireEvent(control_update(control_data), "machineroom")
        else:
            self.log("Invalid control data update request!", lvl=warn)
