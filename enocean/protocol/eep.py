# -*- encoding: utf-8 -*-
import logging
import copy
from pathlib import Path
from xml.etree import ElementTree

import enocean.utils
# Left as a helper
from enocean.protocol.constants import RORG  # noqa: F401


class BaseDataElt:

    logger = logging.getLogger('enocean.protocol.eep.data')
    " Base class inherit from every value data telegram"
    def __init__(self, elt):
        self.description = elt.get("description", "")
        self.shortcut = elt.get("shortcut")
        self.offset = int(elt.get("offset")) if elt.get("offset") else None
        self.size = int(elt.get("size")) if elt.get("size") else None
        self.unit = elt.get("unit") if elt.get("unit") else ""

    def parse_raw(self, bitarray):
        ''' Get raw data as integer, based on offset and size '''
        # TODO: That could be improved and could be check since it raise error
        # self.logger.debug(f"Parse raw data: {bitarray}")
        result = 0
        try:
            # return int(''.join(['1' if digit else '0' for digit in bitarray[self.offset:self.offset + self.size]]), 2)
            for bit in bitarray[self.offset:self.offset + self.size]:
                result = (result << 1) | bit
            return result
        except:
            return 0

    def _set_raw(self, raw_value, bitarray):
        ''' put value into bit array '''
        self.logger.debug(f"_set_raw from offset={self.offset} size={self.size} with value={raw_value}")
        size = self.size
        for digit in range(self.size):
            bitarray[self.offset+digit] = (raw_value >> (size-digit-1)) & 0x01 != 0
        return bitarray


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

    def set_value(self, data, bitarray):
        ''' set given value to target bit in bitarray '''
        bitarray[self.offset] = data
        return bitarray

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
        try:
            self.multiplier = (self.scale_max - self.scale_min) / (self.range_max - self.range_min)
        except Exception as e:
            self.multiplier = 1

    def process_value(self, val):
        # p8 EEP profile documentation
        return self.multiplier * (val - self.range_min) + self.scale_min

    def parse(self, bitarray, status):
        raw = self.parse_raw(bitarray)
        return {
            self.shortcut: {
                'description': self.description,
                'unit': self.unit,
                'value': self.process_value(raw),
                'raw_value': raw,
            }
        }

    def set_value(self, data, bitarray):
        ''' set given numeric value to target field in bitarray '''
        # derive raw value
        # TODO : Confirm method
        # value = (data - self.scale_min) / (self.range_max - self.range_min) * (self.scale_max - self.scale_min) + self.range_min
        value = self.process_value(data)
        return self._set_raw(int(value), bitarray)

    def __str__(self) -> str:
        return f"Data value for {self.description}"


class DataEnumItem(BaseDataElt):

    def __init__(self, elt):
        super().__init__(elt)
        self.value = int(elt.get("value"))

    def __str__(self):
        return f"Enum Item {self.description}"

    def parse(self, val):
        return self.description.replace(" ", "_").lower()


class DataEnumRangeItem(BaseDataElt):

    def __init__(self, elt):
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

    def __str__(self):
        return f"Enum Range Item {self.description}"

    def parse(self, val):
        return self.description.replace(" ", "_").lower().format(value=val)


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

    def get(self, val=None, description=None):
        self.logger.debug(f"Get enum item for value {val} and/or description {description}")
        if val is not None:
            if item := self.items.get(val):
                return item
            for r in self.range_items:
                if r.is_in(val):
                    return r
        elif description: # Get instance based on description
            for item in self.items.values():
                if item.description == description:
                    return item
            for itemrange in self.range_items:
                if itemrange.description == description:
                    return itemrange

    def parse(self, bitarray, status):
        raw = self.parse_raw(bitarray)

        # Find value description
        item = self.get(int(raw))
        self.logger.debug(f"Found item {item} for value {raw}")
        value = item.parse(raw)
        return {
            self.shortcut: {
                'description': item.description if item else "",
                'unit': self.unit,
                'value': value,
                'raw_value': raw,
            }
        }

    def set_value(self, val, bitarray):
        if isinstance(val, int):
            item = self.get(val)
            value = val
        else:
            item = self.get(description=val)
            value = item.value
        if not item:
            raise ValueError(f"Unable to find enum for {val}")
        self.logger.debug(f"Set value to {value}")
        return self._set_raw(int(value), bitarray)


    def __str__(self) -> str:
        return f"Data enum for {self.description} from {self.first} to {self.last}"

    def __len__(self):
        return len(self.items) + len(self.range_items)


class ProfileCommand(DataEnum):
    """ Used to define available commands"""

    def __str__(self) -> str:
        return f"Command enum: {self.description}"


class ProfileData:
    """"""
    logger = logging.getLogger('enocean.protocol.eep.profile')
    def __init__(self, elt):
        self.command = int(elt.get("command")) if elt.get("command") else None
        self.direction = int(elt.get("direction")) if elt.get("direction") else None
        self.bits = int(elt.get("bits")) if elt.get("bits") else 1
        self.items = list()

        for e in elt.iter():
            if e.tag == "status":
                self.items.append(DataStatus(e))
            elif e.tag == "value":
                self.items.append(DataValue(e))
            elif e.tag == "enum":
                self.items.append(DataEnum(e))

    def __str__(self):
        return f"Profile data with {len(self.items)} items | command:{self.command} direction:{self.direction} "

    def get(self, shortcut=None):
        """
        return: BaseDataElt
        """
        self.logger.debug(f"Get profile data for shortcut {shortcut}")
        for item in self.items:
            if item.shortcut == shortcut:
                return item


class Profile:
    logger = logging.getLogger('enocean.protocol.eep.profile')

    def __init__(self, elt, rorg=None, func=None, direction=None, command=None):
        self.rorg = rorg
        self.func = func
        self.type = elt.get("type")
        self.description = elt.get("description")
        if len(elt.findall("command")) > 1:
            raise ValueError("More then 1 command for profile")
        c = elt.find("command")
        if c is not None:
            self.commands = ProfileCommand(c)
            # TODO: Confirm utility
            # if len(self.commands) > len(elt.findall("data")):
            #     Warning(f"{self.rorg}-{self.func}-{self.type} Seems to have less command than possible value")
            #     self.logger.debug(f"commands: {len(self.commands)} data {len(elt.findall("data"))}")
        else:
            self.commands = None
        # Dict of multiple supported datas profile depending on direction or command
        self.datas = dict()
        for p in elt.findall("data"):
            # List all suppoted Profile data based organized on key (command, direction) (None, None) is default
            profile_data = ProfileData(p)
            profile_key = (profile_data.command, profile_data.direction)
            self.datas[profile_key] = profile_data
        # self.datas = [ProfileData(p) for p in elt.findall("data")]
        self.command_item = None
        self.command_data = None

    @property
    def items(self):
        return self.command_data.items

    @property
    def bits(self):
        return self.command_data.bits

    # def __getattr__(self, item):
    #     return getattr(self.command_data, item)


    @property
    def code(self):
        return f"{self.rorg}-{self.func}-{self.type}"

    def __str__(self):
        txt = f"Profile {self.code} about {self.description}"
        if self.commands:
            txt += f" with {len(self.commands)} commands"
        return txt

    def set_command(self, command_id=None, direction=None):
        try:
            self.command_item = self.commands.get(val=command_id)
        except AttributeError:
            self.logger.debug(f"No command support for {self}")
        self.command_data = self.datas.get((command_id, direction))

    def get(self, command=None, direction=None):
        if command and direction:
            # TODO: Confirm this limitation
            self.logger.warning("Command and Direction are specified but only one at a time should be use")
        if command and not self.commands:
            self.logger.error("A command is specified but not supported by profile")
            # raise ValueError("A command is specified but not supported by profile")
        elif self.commands and not command:
            # Do not raise Exception since it break tests, however this is an error anyway
            # raise ValueError("Command not specified but profile support multiple commands")
            self.logger.warning("Command is not specified but the profile support multiples commands")
            return self.datas.get((1, direction)) # TODO: Confirm that first command must be decoded if not specified
        # elif command:
        #     print("Command selected:", command, type(command))
        #
        # if direction:
        #     print("Direction selected:", direction, type(direction))
        #     print(self, self.datas)
        # TODO: should respond self with direction, command set
        command_item = self.commands.get(val=command)
        telegram_data = self.datas.get((command, direction))
        c = copy.copy(self)
        m = Message(telegram_data, command=command_item, direction=direction)
        print(m)
        c.set_command(command_id=command, direction=direction)
        try:
            c.set_command(command_id=command, direction=direction)
        except Exception:
            self.logger.debug("Profile do not support datas")
        # return self.datas.get((command, direction))
        return c

    def get_message_form(self, command=None, direction=None):
        if command and direction:
            # TODO: Confirm this limitation
            self.logger.warning("Command and Direction are specified but only one at a time should be use")
        if command and not self.commands:
            self.logger.error("A command is specified but not supported by profile")
            # raise ValueError("A command is specified but not supported by profile")
        elif self.commands and not command:
            # Do not raise Exception since it break tests, however this is an error anyway
            # raise ValueError("Command not specified but profile support multiple commands")
            self.logger.warning("Command is not specified but the profile support multiples commands")
            return self.datas.get((1, direction)) # TODO: Confirm that first command must be decoded if not specified

        command_item = self.commands.get(val=command)
        telegram_data = self.datas.get((command, direction))
        return Message(telegram_data, command=command_item, direction=direction)

    # def get_item_shortcut(self, shortcut):
    #     if self.commands and self.commands.shortcut == shortcut:
    #         return self.commands
    #     for data_elt in self.datas.values():
    #         if data_elt.shortcut == shortcut:
    #             return data_elt
    #
    # def map_item_value(self, shortcut, value):
    #     if item := self.get_item_shortcut(shortcut):
    #         if val := item.get(val=value):
    #             return val


class Profiles:

    def __init__(self, elt):
        self.func = elt.get("func")
        self.description = elt.get("description")
        self.profiles = [Profile(p) for p in elt.findall("profile")]


class Message:
    logger = logging.getLogger('enocean.protocol.eep.message')

    def __init__(self, telegram_data, command=None, direction=None):
        self.telegram_data = telegram_data
        self.command_item = command
        self.direction = direction

    def __str__(self):
        return f"Message {self.telegram_data} with command {self.command_item}"
    @property
    def items(self):
        return self.telegram_data.items

    @property
    def bits(self):
        return self.telegram_data.bits

    def get_values(self, bitarray, status):
        ''' Get keys and values from bitarray '''
        output = dict()
        for source in self.items:
            if source.shortcut == "CMD":
                val = source.parse(bitarray, status)
                self.logger.debug(f"Identify command description for item {val}")
                val["CMD"]["value"] = self.command_item.description
                output.update(val)
            else:
                output.update(source.parse(bitarray, status))
        self.logger.debug(f"get_values {output}")
        return output

    def set_values(self, data, status, properties):
        ''' Update data based on data contained in properties
        profile: Profile
        '''
        self.logger.debug(f"Set value data={data} status={status} properties={properties}")
        # self.logger.debug(f"Profile with selected command {self.profile.command_item} {self.profile.command_data}")

        for shortcut, value in properties.items():
            # find the given property from EEP
            if shortcut == "CMD":
                target = self.command_item
            else:
                target = self.telegram_data.get(shortcut)
                self.logger.debug(f"Get {target} for shortcut {shortcut}")
            self.logger.debug(f"Set bitarray for target type {type(target)}")
            if isinstance(target, DataStatus):
                status = target.set_value(value, data)
            else:
                data = target.set_value(value, data)
        return data, status


class EEP(object):
    logger = logging.getLogger('enocean.protocol.eep')

    def __init__(self):
        self.init_ok = False
        self.telegrams = {}

        try:
            self.logger.debug("Start loading EEP xml files")
            # eep_path = Path(__file__).parent.absolute().joinpath('EEP.xml')
            # tree = ElementTree.parse(eep_path)
            # tree_root = tree.getroot()
            # self.__load_xml(tree_root)
            eep_path = Path(__file__).parent.absolute().joinpath('eep')
            self.__load_xml_files(eep_path)
            self.logger.debug("EEP loaded")
            self.init_ok = True
        except IOError:
            # Impossible to test with the current structure?
            # To be honest, as the XML is included with the library,
            # there should be no possibility of ever reaching this...
            self.logger.warning('Cannot load protocol file!')
            self.init_ok = False

    def __load_xml(self, et):
        self.telegrams = {
            enocean.utils.from_hex_string(telegram.attrib['rorg']): {
                enocean.utils.from_hex_string(function.attrib['func']): {
                    enocean.utils.from_hex_string(profile.attrib['type'], ): Profile(profile, rorg=telegram.attrib['rorg'], func=function.attrib['func'])
                    for profile in function.findall('profile')
                }
                for function in telegram.findall('profiles')
            }
            for telegram in et.findall('telegram')
        }

    def __load_xml_files(self, folder_path):
        """ Used for case of usage of xml profile file per profile"""
        for file_path in folder_path.glob("**/*.xml"):
            tree = ElementTree.parse(file_path)
            tree_root = tree.getroot()
            telegram = tree_root.find("telegram")
            function = telegram.find("profiles")
            profile = function.find("profile")

            rorg_hex = telegram.attrib['rorg']
            func_hex = function.attrib['func']

            rorg = enocean.utils.from_hex_string(rorg_hex)
            func = enocean.utils.from_hex_string(func_hex)
            type_ = enocean.utils.from_hex_string(profile.attrib['type'])

            if rorg in self.telegrams:
                if func in self.telegrams[rorg]:
                    if type_ in self.telegrams[rorg][func]:
                        continue # Should not occur
                    else:
                        self.telegrams[rorg][func].update({type_: Profile(profile, rorg=rorg_hex, func=func_hex)})
                else:
                    self.telegrams[rorg].update({func : {type_ : Profile(profile, rorg=rorg_hex, func=func_hex)}})
            else:
                self.telegrams.update({rorg : {func : {type_ : Profile(profile, rorg=rorg_hex, func=func_hex)}}})

    # def get_command_id(self, bitarray, eep_rorg, rorg_func, rorg_type):
    #     try:
    #         profile = self.telegrams[eep_rorg][rorg_func][rorg_type]
    #         if profile.commands:
    #             command_id = profile.commands.parse_raw(bitarray)
    #             # command_id = self.parse_raw(bitarray, profile.commands.offset, profile.commands.size)
    #             return command_id
    #     except Exception as e:
    #         self.logger.warning('Cannot find rorg %s func %s type %s in EEP!', hex(eep_rorg), hex(rorg_func),
    #                             hex(rorg_type))

    def find_profile(self, eep_rorg, rorg_func, rorg_type, direction=None, command=None):
        ''' Find profile and data description, matching RORG, FUNC and TYPE

        return: ProfileData
        '''
        if not self.init_ok:
            self.logger.warning('EEP.xml not loaded!')
            return None
        try:
            profile = self.telegrams[eep_rorg][rorg_func][rorg_type]
        except Exception as e:
            self.logger.warning('Cannot find rorg %s func %s type %s in EEP!', hex(eep_rorg), hex(rorg_func),
                                hex(rorg_type))
            return None
        return profile.get(direction=direction, command=command)

    def get_eep(self, eep_rorg, rorg_func, rorg_type):
        if not self.init_ok:
            self.logger.warning('EEP.xml not loaded!')
            return None
        try:
            return self.telegrams[eep_rorg][rorg_func][rorg_type]
        except Exception as e:
            self.logger.warning('Cannot find rorg %s func %s type %s in EEP!', hex(eep_rorg), hex(rorg_func),
                                hex(rorg_type))

    def get_values(self, profile, bitarray, status):
        ''' Get keys and values from bitarray '''
        output = dict()
        if not self.init_ok or profile is None:
            return output
        for source in profile.items:
            self.logger.debug(f"Parse element {source} for value data={bitarray} status={status}")
            if source.shortcut == "CMD":
                val = source.parse(bitarray, status)
                self.logger.debug(f"Identify command description for item {val}")
                val["CMD"]["value"] = profile.command_item.description
                output.update(val)
            else:
                output.update(source.parse(bitarray, status))
        self.logger.debug(f"get_values {output}")
        return output

    def set_values(self, profile, data, status, properties):
        ''' Update data based on data contained in properties
        profile: Profile
        '''
        self.logger.debug(f"Set value profile {profile} data={data} status={status} properties={properties}")
        self.logger.debug(f"Profile with selected command {profile.command_item} {profile.command_data}")
        if not self.init_ok or profile is None:
            return data, status

        for shortcut, value in properties.items():
            # # find the given property from EEP
            # target = profile.get(shortcut=shortcut)
            # if not target:
            #     # TODO: Should we raise an error?
            #     self.logger.warning('Cannot find data description for shortcut %s', shortcut)
            #     continue
            # # update bit_data
            if shortcut == "CMD":
                target = profile.commands
            else:
                target = profile.command_data.get(shortcut)
                self.logger.debug(f"Get {target} for shortcut {shortcut}")
            self.logger.debug(f"Set bitarray for target type {type(target)}")
            if isinstance(target, DataStatus):
                status = target.set_value(value, data)
            else:
                data = target.set_value(value, data)
        return data, status
