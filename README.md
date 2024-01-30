# Python EnOcean #

A Python library for reading and controlling [EnOcean](http://www.enocean.com/) devices.

Based on work of [kipe](https://github.com/kipe/enocean) and [mak-gitdev](https://github.com/mak-gitdev/enocean).

## Fork modification ##


- Remove Beautifulsoup4 dependencies (use ElementTree) lxml should work without effort
- Defined EEP class to avoid parsing xml on fly
- Use one xml file per EEP
- Added some EEP
- Support >= 3.8 (remove OrderedDict, use f-string, use PEP 572)
- Added descriptions to metrics