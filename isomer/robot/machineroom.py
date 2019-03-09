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

Module: Machineroom
===================

Engine, Rudder and miscellaneous machine roome control operations.

Currently this is only useable in conjunction with Hackerfleet's MS 0x00
NeoCortex board.


"""

import sys

# TODO: Kick out 2.x compat
import six
from circuits.io import Serial
from circuits.io.events import write
from random import randint

import glob
from isomer.component import ConfigurableComponent
from isomer.component import handler
from isomer.logger import isolog, critical, debug, warn, verbose

try:
    import serial
except ImportError:
    serial = None
    isolog("No serial port found. Serial bus remote control devices will be "
           "unavailable, install requirements.txt!",
           lvl=critical, emitter="MR")


def serial_ports():
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system

        Courtesy: Thomas ( http://stackoverflow.com/questions/12090503
        /listing-available-com-ports-with-python )
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result


class Machineroom(ConfigurableComponent):
    """
    Enables simple robotic control by translating high level events to
    servo control commands and transmitting them to a connected controller
    device.

    This prototype has built-in low level language support for the MS 0x00
    controller but can be easily adapted for other hardware servo/engine
    controllers.
    """

    channel = "machineroom"

    configprops = {
        'baudrate': {
            'type': 'integer',
            'title': 'Baudrate',
            'description': 'Communication data rate',
            'default': 9600
        },
        'buffersize': {
            'type': 'integer',
            'title': 'Buffersize',
            'description': 'Communication buffer size',
            'default': 4096
        },
        'serialfile': {
            'type': 'string',
            'title': 'Serial port device',
            'description': 'File descriptor to access serial port',
            'default': '/dev/ttyACM0'
        },
    }

    servo = b's'
    pin = b'p'
    version = b'v'
    message = b'm'
    sep = b','
    # TODO: Kick out 2.x compat
    if six.PY2:
        terminator = chr(13)
    else:
        # noinspection PyArgumentList
        terminator = bytes(chr(13), encoding="ascii")

    def __init__(self, *args, **kwargs):
        super(Machineroom, self).__init__('MR', *args, **kwargs)
        self.log("Machineroom starting")

        self.maestro = True

        self.targets = {
            'machine': 1,
            'rudder': 0,
            'pump': 2
        }

        self.controller_mapping = {
            'axes': {
                1: {
                    'name': 'machine',
                    'flags': ['inverted'],
                },
                2: {
                    'name': 'rudder'
                }
            },
            'buttons': {
                3: {
                    'name': 'pump'
                }
            }
        }

        self._rudder_channel = 0
        self._machine_channel = 1
        self._pump_channel = 2  # TODO: Make this a dedicated singleton call?
        #  e.g. pumpon/pumpoff.. not so generic

        self._values = {}

        for item in self.targets.values():
            self._values[item] = 0

        self._serial_open = False

        if self.config.serialfile != '':
            try:
                self.serial = Serial(self.config.serialfile,
                                     self.config.baudrate,
                                     self.config.buffersize, timeout=5,
                                     channel="port").register(self)

                # Workaround for https://github.com/circuits/circuits/issues/252
                # self.serial._encoding = 'ascii'
            except Exception as e:
                self.log("Problem with serial port: ", e, type(e),
                         lvl=critical)
        else:
            self.log("No serial port configured!", lvl=warn)

        self.log("Running")

    def _send_command(self, command):
        if not self._serial_open:
            self.log("Cannot transmit, serial port not available!", lvl=warn)
            return

        if not isinstance(command, bytes):
            command = bytes(command, encoding='ascii')

        if not self.maestro:
            cmd = command + self.terminator
        else:
            cmd = command
        # cmdbytes = bytes(cmd, encoding="ascii")

        self.log("Transmitting bytes: ", "\n", cmd, lvl=critical)
        if len(cmd) != 3:
            self.log('Illegal command:', cmd, lvl=critical)
            return

        self.fireEvent(write(cmd), "port")

    @handler("opened", channel="port")
    def opened(self, *args):
        """Initiates communication with the remote controlled device.

        :param args:
        """
        self._serial_open = True

        if not self.maestro:
            self.log("Opened: ", args, lvl=debug)
            self._send_command(b'l,1')  # Saying hello, shortly
            self.log("Turning off engine, pump and neutralizing rudder")
            self._send_command(b'v')
        self._handle_servo(self._machine_channel, 0)
        self._handle_servo(self._rudder_channel, 127)
        self._set_digital_pin(self._pump_channel, 0)

        if not self.maestro:
            # self._send_command(b'h')
            self._send_command(b'l,0')
            self._send_command(b'm,HFOS Control')

    def _handle_servo(self, channel, value):
        """

        :param channel:
        :param value:
        """
        if self.maestro:
            # lsb = value & 0x7f  # 7 bits for least significant byte
            # msb = (value >> 7) & 0x7f  # shift 7 and take next 7 bits for msb
            # command = chr(0x04) + chr(channel) + chr(lsb) + chr(msb)
            value = min(value, 255)
            command = bytes([0xff]) + bytes([channel]) + bytes([value])
        else:
            command = self.servo + self.sep + bytes([channel]) + self.sep + bytes(
                [value])

        self._send_command(command)

    def _set_digital_pin(self, pin, value):
        """

        :param pin:
        :param value:
        """
        mode = 255 if value >= 127 else 0

        if not self.maestro:
            self._send_command(
                self.pin + self.sep + bytes([pin]) + self.sep + bytes([mode]))
        else:
            self._handle_servo(pin, mode)

    @handler("control_update")
    def on_control_update(self, event):
        """
        A remote control update request containing control data that has to be
        analysed according to the selected controller configuration.

        :param event: machine_update
        """
        self.log("Control update request: ", event.controldata, lvl=verbose)

        for key, item in self.controller_mapping['axes'].items():
            raw_value = event.controldata['axes'][key]
            if raw_value < -1 or raw_value > 1:
                self.log('Incorrect control value received:', raw_value, lvl=warn)
                return

            if 'inverted' in item.get('flags', []):
                new_value = min(128 - int(raw_value * 128), 255)
            else:
                new_value = min(128 + int(raw_value * 128), 255)
            name = item['name']
            target = self.targets[name]

            if self._values[target] != new_value:
                self.log('Setting %s (%i) to %i' % (name, target, new_value), lvl=debug)
                self._handle_servo(target, new_value)
                self._values[target] = new_value

        for key, item in self.controller_mapping['buttons'].items():
            new_value = event.controldata['buttons'][key]
            name = item['name']
            target = self.targets[name]

            if self._values[target] != new_value:
                self.log('Setting %s (%i) to %i' % (name, target, new_value), lvl=debug)
                self._set_digital_pin(target, new_value)
                self._values[target] = new_value

    @handler("machine")
    def on_machinerequest(self, event):
        """
        Sets a new machine speed.

        :param event:
        """
        self.log("Updating new machine power: ", event.controlvalue)
        self._handle_servo(self._machine_channel, event.controlvalue)
        self._values['machine'] = event.controlvalue

    @handler("rudder")
    def on_rudderrequest(self, event):
        """
        Sets a new rudder angle.

        :param event:
        """
        self.log("Updating new rudder angle: ", event.controlvalue)
        self._handle_servo(self._rudder_channel, event.controlvalue)
        self._values['rudder'] = event.controlvalue

    @handler("pump")
    def on_pumprequest(self, event):
        """
        Activates or deactivates a connected pump.

        :param event:
        """
        self.log("Updating pump status: ", event.controlvalue)
        self._set_digital_pin(self._pump_channel, event.controlvalue)
        self._values['pump'] = event.controlvalue

    @handler("read", channel="port")
    def read(self, *args):
        """
        Handles incoming data from the machine room hardware control system.

        :param args:
        """
        self.log("Data received from machineroom: ", args)

    @handler("ping")
    def on_ping(self):
        """
        Demo function for debugging purposes.

        """
        # TODO: Delete me
        self.log("Pinging")
        self._handle_servo(self._rudder_channel, randint(0, 255))
