# -*- encoding: utf-8 -*-
import logging

from enocean.protocol.eep import EEP


class Equipment(object):
    ''' Representation of device/sensor as EnOcean use the term Equipement '''

    eep = EEP()
    logger = logging.getLogger('enocean.protocol.packet')

    def __init__(self, address, rorg=None, func=None, type_=None, name=None) -> None:
        self.address = address
        self.rorg = rorg
        self.func = func
        self.type = type_
        self.name = name
        self.profile = self.eep.get_eep(rorg, func, type_)

    @property
    def description(self):
        return self.profile.description

    @property
    def eep_code(self):
        return f"{hex(self.rorg)}-{hex(self.func)}-{hex(self.type)}"

    def __str__(self) -> str:
        if self.name:
            return f"Device {self.name} address {self.address} eep {self.eep_code}"
        return f"Device {self.address} eep {self.eep_code}"

