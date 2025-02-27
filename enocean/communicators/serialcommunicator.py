# -*- encoding: utf-8 -*-
import logging
import serial
import time

from enocean.communicators.communicator import Communicator


class SerialCommunicator(Communicator):
    ''' Serial port communicator class for EnOcean radio '''
    logger = logging.getLogger('enocean.communicators.SerialCommunicator')

    def __init__(self, port='/dev/ttyAMA0', baudrate=57600, timeout=0.1, callback=None):
        super(SerialCommunicator, self).__init__(callback)
        # Initialize serial port
        self.__port = port
        self.__baudrate = baudrate
        self.__ser = serial.Serial(port, baudrate, timeout=timeout)

    def run(self):
        self.logger.info('SerialCommunicator started')
        while not self._stop_flag.is_set():
            # If there's messages in transmit queue
            # send them
            while True:
                packet = self._get_from_send_queue()
                if not packet:
                    break
                try:
                    self.__ser.write(bytearray(packet.build()))
                except serial.SerialException:
                    self.stop()

            # Read chars from serial port as hex numbers
            try:
                self._buffer.extend(bytearray(self.__ser.read(16)))
            except serial.SerialException:
                self.logger.error(f'Serial port exception! (device disconnected or multiple access on port {self.__port} ?)')
                self.stop()
            try:
                self.parse()
            except Exception as e:
                self.logger.error(f'Exception occured while parsing: {e}')
            time.sleep(0)

        self.__ser.close()
        self.logger.info('SerialCommunicator stopped')
