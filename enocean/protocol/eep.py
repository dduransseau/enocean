# -*- encoding: utf-8 -*-
from __future__ import print_function, unicode_literals, division, absolute_import
import logging
from pathlib import Path
from collections import OrderedDict
from xml.etree import ElementTree

import enocean.utils
# Left as a helper
from enocean.protocol.constants import RORG  # noqa: F401

class BaseDataElt:
    " Base class inherit from every value data telegram"
    def __init__(self, elt):
        self.description = elt.get("description")
        self.shortcut = elt.get("shortcut")
        self.offset = int(elt.get("offset")) if elt.get("offset") else None
        self.size = int(elt.get("size")) if elt.get("size") else None
        self.unit = elt.get("unit") if elt.get("unit") else ""

    def parse_raw(self, bitarray):
        ''' Get raw data as integer, based on offset and size '''
        return int(''.join(['1' if digit else '0' for digit in bitarray[self.offset:self.offset + self.size]]), 2)


class DataStatus(BaseDataElt):
    """ Status element
    ex: <status description="T21" shortcut="T21" offset="2" size="1" />
    """

    def __str__(self) -> str:
        return f"Data status for {self.description}"

    def parse(self, bitarray, status):
        ''' Get boolean value, based on the data in XML '''
        raw_value = self.parse_raw(status)
        return {
            self.shortcut: {
                'description': self.description,
                'unit': self.unit,
                'value': True if raw_value else False,
                'raw_value': raw_value,
            }
        }

class DataValue(BaseDataElt):
    """
    ex: <value description="Temperature (linear)" shortcut="TMP" offset="16" size="8" unit="°C">
            <range>
              <min>255</min>
              <max>0</max>
            </range>
            <scale>
              <min>-40.000000</min>
              <max>0.000000</max>
            </scale>
          </value>
    """
    def __init__(self, elt):
        super().__init__(elt)
        if r := elt.find("range"):
            self.is_range = True
            self.range_min = float(r.find("min").text)
            self.range_max = float(r.find("max").text)
        if s := elt.find("scale"):
            self.scale = True
            self.scale_min = float(s.find("min").text)
            self.scale_max = float(s.find("max").text)

    def process_value(self, val):
        return (self.scale_max - self.scale_min) / (self.range_max - self.range_min) * (val - self.range_min) + self.scale_min
    def parse(self, bitarray, status):
        raw = self.parse_raw(bitarray)
        # print(f"Data raw {raw}")
        return {
            self.shortcut: {
                'description': self.description,
                'unit': self.unit,
                # TODO: Figure out this logic
                'value': (self.scale_max - self.scale_min) / (self.range_max - self.range_min)
                         * (raw - self.range_min) + self.scale_min,
                'raw_value': raw,
            }
        }

    def __str__(self) -> str:
        return f"Data value for {self.description}"


class DataEnumItem(BaseDataElt):

    def __init__(self, elt):
        super().__init__(elt)
        self.value = int(elt.get("value"))


class DataEnumRangeItem(BaseDataElt):

    def __init__(self, elt, *args, **kwargs):
        super().__init__(elt)
        self.start = int(elt.get("start"))
        self.end = int(elt.get("end"))

    @property
    def limit(self):
        return (self.start, self.end,)

    def is_in(self, value):
        if self.start <= value <= self.end:
            return True

    def range(self):
        return range(self.start, self.end+1)

    def __eq__(self, __value: object) -> bool:
        return super().__eq__(__value)


class DataEnum(BaseDataElt):
    """ Base class used for Enum and EnumRange"""

    def __init__(self, elt):
        super().__init__(elt)
        self.items = dict()
        self.range_items = list()
        for item in elt.findall("item"):
            i = DataEnumItem(item)
            self.items[i.value] = i
        for ritem in elt.findall("rangeitem"):
            r = DataEnumRangeItem(ritem)
            self.range_items.append(r)

    @property
    def first(self):
        # Find the first valid value of enum
        min = 256
        for i in self.items.keys():
            if i < min:
                min = i
        for i in self.range_items:
            if i.start < min:
                min = i.start
        return min

    @property
    def last(self):
        # find the last valid value of enum
        max = 0
        for i in self.items.values():
            if i.value > max:
                max = i.value
        for i in self.range_items:
            if i.end > max:
                max = i.end
        return max

    def get(self, val):
        if item := self.items.get(val):
            return item
        for r in self.range_items:
            if r.is_in(val):
                return r

    def parse(self, bitarray, status):
        raw = self.parse_raw(bitarray)

        # Find value description.
        item = self.get(int(raw))

        return {
            self.shortcut: {
                'description': self.description,
                'unit': self.unit,
                'value': item.description,
                'raw_value': raw,
            }
        }

    def __str__(self) -> str:
        return f"Data enum for {self.description} from {self.first} to {self.last}"

    def __len__(self):
        return len(self.items) + len(self.range_items)


class ProfileCommand(DataEnum):
    """ Used to define available commands"""


class ProfileData:
    """"""
    def __init__(self, elt):
        self.command = int(elt.get("command")) if elt.get("command") else None
        self.direction = int(elt.get("direction")) if elt.get("direction") else None
        self.items = list()

        for e in elt.iter():
            if e.tag == "status":
                self.items.append(DataStatus(e))
            elif e.tag == "value":
                self.items.append(DataValue(e))
            elif e.tag == "enum":
                self.items.append(DataEnum(e))

    def __str__(self):
        return f"Profile data command {self.command} and direction {self.direction} with {len(self.items)} items"

class Profile:

    def __init__(self, elt, rorg=None, func=None):
        self.rorg = rorg
        self.func = func
        self.type = elt.get("type")
        self.description = elt.get("description")
        if len(elt.findall("command")) > 1:
            raise ValueError("More then 1 command for profile")
        c = elt.find("command")
        if c is not None:
            self.commands = ProfileCommand(c)
            if len(self.commands) > len(elt.findall("data")):
                Warning(f"{self.rorg}-{self.func}-{self.type} Seems to have less command than possible value"
                        f" commands: {len(self.commands)} data {len(elt.findall("data"))}")
        else:
            self.commands = None
        self.datas = dict()
        for p in elt.findall("data"):
            profile_data = ProfileData(p)
            profile_key = (profile_data.command, profile_data.direction)
            self.datas[profile_key] = profile_data
        # self.datas = [ProfileData(p) for p in elt.findall("data")]

    @property
    def code(self):
        return f"{self.rorg}-{self.func}-{self.type}"

    def __str__(self):
        txt = f"Profile {self.code} about {self.description}"
        if self.commands:
            txt += f" with {len(self.commands)} commands"
        return txt

    def get(self, command=None, direction=None):
        # TODO: Confirm this exception
        if command and direction:
            Warning("Command and Direction are specified but only one at a time can be use")
        if command and not self.commands:
            raise ValueError("A command is specified but not supported by profile")
        elif self.commands and not command:
            raise ValueError("Command not specified but profile support multiple commands")
        # elif command:
        #     print("Command selected:", command, type(command))
        #
        # if direction:
        #     print("Direction selected:", direction, type(direction))
        #     print(self, self.datas)
        return self.datas.get((command, direction))


class Profiles:

    def __init__(self, elt):
        self.func = elt.get("func")
        self.description = elt.get("description")
        self.profiles = [Profile(p) for p in elt.findall("profile")]


class EEP(object):
    logger = logging.getLogger('enocean.protocol.eep')

    def __init__(self):
        self.init_ok = False
        self.telegrams = {}

        eep_path = Path(__file__).parent.absolute().joinpath('EEP.xml')
        try:
            with open(eep_path, 'r', encoding="utf-8") as xml_file:
                self.soup = ElementTree.fromstring(xml_file.read())
            self.__load_xml()
            self.init_ok = True
        except IOError:
            # Impossible to test with the current structure?
            # To be honest, as the XML is included with the library,
            # there should be no possibility of ever reaching this...
            self.logger.warn('Cannot load protocol file!')
            self.init_ok = False

    def __load_xml(self):
        self.telegrams = {
            enocean.utils.from_hex_string(telegram.attrib['rorg']): {
                enocean.utils.from_hex_string(function.attrib['func']): {
                    enocean.utils.from_hex_string(type.attrib['type'], ): type
                    for type in function.findall('profile')
                }
                for function in telegram.findall('profiles')
            }
            for telegram in self.soup.findall('telegram')
        }
        self.telegrams2 = {
            enocean.utils.from_hex_string(telegram.attrib['rorg']): {
                enocean.utils.from_hex_string(function.attrib['func']): {
                    enocean.utils.from_hex_string(profile.attrib['type'], ): Profile(profile, telegram.attrib['rorg'], function.attrib['func'])
                    for profile in function.findall('profile')
                }
                for function in telegram.findall('profiles')
            }
            for telegram in self.soup.findall('telegram')
        }

    @staticmethod
    def _set_raw(target, raw_value, bitarray):
        ''' put value into bit array '''
        offset = int(target.get('offset'))
        size = int(target.get('size'))
        for digit in range(size):
            bitarray[offset+digit] = (raw_value >> (size-digit-1)) & 0x01 != 0
        return bitarray

    @staticmethod
    def _get_rangeitem(source, raw_value):
        for rangeitem in source.findall('rangeitem'):
            if raw_value in range(int(rangeitem.get('start', -1)), int(rangeitem.get('end', -1)) + 1):
                return rangeitem

    def _set_value(self, target, value, bitarray):
        ''' set given numeric value to target field in bitarray '''
        # derive raw value
        rng = target.find('range')
        rng_min = float(rng.find('min').text)
        rng_max = float(rng.find('max').text)
        scl = target.find('scale')
        scl_min = float(scl.find('min').text)
        scl_max = float(scl.find('max').text)
        raw_value = (value - scl_min) * (rng_max - rng_min) / (scl_max - scl_min) + rng_min
        # store value in bitfield
        return self._set_raw(target, int(raw_value), bitarray)

    def _set_enum(self, target, value, bitarray):
        ''' set given enum value (by string or integer value) to target field in bitarray '''
        # derive raw value
        if isinstance(value, int):
            # check whether this value exists
            if target.find('item', {'value': value}) or self._get_rangeitem(target, value):
                # set integer values directly
                raw_value = value
            else:
                raise ValueError('Enum value "%s" not found in EEP.' % (value))
        else:
            value_item = target.find('item', {'description': value})
            if value_item is None:
                raise ValueError('Enum description for value "%s" not found in EEP.' % (value))
            raw_value = int(value_item['value'])
        return self._set_raw(target, raw_value, bitarray)

    @staticmethod
    def _set_boolean(target, data, bitarray):
        ''' set given value to target bit in bitarray '''
        bitarray[int(target['offset'])] = data
        return bitarray

    def find_profile(self, bitarray, eep_rorg, rorg_func, rorg_type, direction=None, command=None):
        ''' Find profile and data description, matching RORG, FUNC and TYPE '''
        if not self.init_ok:
            self.logger.warning('EEP.xml not loaded!')
            return None
        try:
            profile = self.telegrams2[eep_rorg][rorg_func][rorg_type]
        except Exception as e:
            self.logger.warning('Cannot find rorg %s func %s type %s in EEP!', hex(eep_rorg), hex(rorg_func),
                                hex(rorg_type))
            return None
        return profile.get(direction=direction, command=command)

    def get_values(self, profile, bitarray, status):
        ''' Get keys and values from bitarray '''
        if not self.init_ok or profile is None:
            return [], {}
        output = dict()
        for source in profile.items:
            output.update(source.parse(bitarray, status))
        return output.keys(), output

    def set_values(self, profile, data, status, properties):
        ''' Update data based on data contained in properties '''
        if not self.init_ok or profile is None:
            return data, status

        for shortcut, value in properties.items():
            # find the given property from EEP
            target = profile.find(shortcut=shortcut)
            if not target:
                # TODO: Should we raise an error?
                self.logger.warning('Cannot find data description for shortcut %s', shortcut)
                continue

            # update bit_data
            if target.name == 'value':
                data = self._set_value(target, value, data)
            if target.name == 'enum':
                data = self._set_enum(target, value, data)
            if target.name == 'status':
                status = self._set_boolean(target, value, status)
        return data, status
