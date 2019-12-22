#!/usr/bin/env python3
#
# Copyright (C) 2017-2019 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import sys
import os
import jinja2

from copy import deepcopy
from vyos.config import Config
from vyos import ConfigError

# Please be careful if you edit the template.
config_file = "/etc/default/lldpd"
lldp_tmpl = """
### Autogenerated by lldp.py ###
DAEMON_ARGS="-M4{% if snmp %} -x{% endif %}{% if addr %} -m {{ addr }}{% endif %}{% if cdp %} -c{% endif %}{% if edp %} -e{% endif %}{% if fdp %} -f{% endif %}{% if sonmp %} -s{% endif %}"

"""

vyos_config_file = "/etc/lldpd.d/01-vyos.conf"
vyos_tmpl = """
### Autogenerated by lldp.py ###

configure system platform VyOS
configure system description "VyOS {{ description }}"
{% if listen_on %}
configure system interface pattern "{{ listen_on | join(",") }}"
{% endif %}

"""

default_config_data = {
    "options": '',
    "interface_list": '',
    "location": ''
}

def get_options(config):
    options = {}
    config.set_level('service lldp')

    options['listen_vlan'] = config.exists('listen-vlan')
    options['addr'] = config.return_value('management-address')

    snmp = config.exists('snmp enable')
    options["snmp"] = snmp
    if snmp:
        config.set_level('')
        options["sys_snmp"] = config.exists('service snmp')
        config.set_level('service lldp')

    config.set_level('service lldp legacy-protocols')
    options['cdp'] = config.exists('cdp')
    options['edp'] = config.exists('edp')
    options['fdp'] = config.exists('fdp')
    options['sonmp'] = config.exists('sonmp')

    # start with an unknown version information
    options['description'] = 'unknown'
    options['listen_on'] = []

    return options

def get_interface_list(config):
    config.set_level('service lldp')
    intfs_names = config.list_nodes('interface')
    if len(intfs_names) < 0:
        return 0

    interface_list = []
    for name in intfs_names:
        config.set_level('service lldp interface {0}'.format(name))
        disable = config.exists('disable')
        intf = {
            'name': name,
            'disable': disable
        }
        interface_list.append(intf)
    return interface_list


def get_location_intf(config, name):
    path = 'service lldp interface {0}'.format(name)
    config.set_level(path)
    if config.exists('location'):
        return 0

    config.set_level('{} location'.format(path))
    civic_based = {}
    elin = None
    coordinate_based = {}

    if config.exists('civic-based'):
        config.set_level('{} location civic-based'.format(path))
        cc = config.return_value('country-code')
        civic_based['country_code'] = cc
        civic_based['ca_type'] = []
        ca_types_names = config.list_nodes('ca-type')
        if ca_types_names:
            for ca_types_name in ca_types_names:
                config.set_level('{0} location civic-based ca-type {1}'.format(path, ca_types_name))
                ca_val = config.return_value('ca-value')
                ca_type = {
                    'name': ca_types_name,
                    'ca_val': ca_val
                }
                civic_based['ca_type'].append(ca_type)

    elif config.exists('elin'):
        elin = config.return_value('elin')

    elif config.exists('coordinate-based'):
        config.set_level('{} location coordinate-based'.format(path))

        coordinate_based['altitude'] = config.return_value('altitude')
        coordinate_based['latitude'] = config.return_value('latitude')
        coordinate_based['longitude'] = config.return_value('longitude')
        coordinate_based['datum'] = config.return_value('datum')

    intf = {
        'name': name,
        'civic_based': civic_based,
        'elin': elin,
        'coordinate_based': coordinate_based

    }
    return intf


def get_location(config):
    config.set_level('service lldp')
    intfs_names = config.list_nodes('interface')
    if len(intfs_names) < 0:
        return 0

    if config.exists('disable'):
        return 0

    intfs_location = []
    for name in intfs_names:
        intf = get_location_intf(config, name)
        intfs_location.append(intf)

    return intfs_location


def get_config():
    lldp = deepcopy(default_config_data)
    conf = Config()
    if not conf.exists('service lldp'):
        return None
    else:
        lldp['options'] = get_options(conf)
        lldp['interface_list'] = get_interface_list(conf)
        lldp['location'] = get_location(conf)

        return lldp


def verify(lldp):
    # bail out early - looks like removal from running config
    if lldp is None:
        return

    # check location
    for location in lldp['location']:
        # check civic-based
        if len(location['civic_based']) > 0:
            if len(location['coordinate_based']) > 0 or location['elin']:
                raise ConfigError('Can only configure 1 location type for interface {0}'.format(location['name']))

            # check country-code
            if not location['civic_based']['country_code']:
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'must configure the country code'.format(location['name']))

            if not re.match(r'^[a-zA-Z]{2}$', location['civic_based']['country_code']):
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'country-code must be 2 characters'.format(location['name']))
            # check ca-type
            if len(location['civic_based']['ca_type']) < 0:
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'must define at least 1 ca-type'.format(location['name']))

            for ca_type in location['civic_based']['ca_type']:
                if not int(ca_type['name']) in range(0, 129):
                    raise ConfigError('Invalid location for interface {0}:\n' \
                                      'ca-type must between 0-128'.format(location['name']))

                if not ca_type['ca_val']:
                    raise ConfigError('Invalid location for interface {0}:\n' \
                                      'must configure the ca-value for ca-type {1}'.format(location["name"],ca_type['name']))

        # check coordinate-based
        elif len(location['coordinate_based']) > 0:
            # check longitude and latitude
            if not location['coordinate_based']['longitude']:
                raise ConfigError('Must define longitude for interface {0}'.format(location['name']))

            if not location['coordinate_based']['latitude']:
                raise ConfigError('Must define latitude for interface {0}'.format(location['name']))

            if not re.match(r'^(\d+)(\.\d+)?[nNsS]$', location['coordinate_based']['latitude']):
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'latitude should be a number followed by S or N'.format(location['name']))

            if not re.match(r'^(\d+)(\.\d+)?[eEwW]$', location['coordinate_based']['longitude']):
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'longitude should be a number followed by E or W'.format(location['name']))

            # check altitude and datum if exist
            if location['coordinate_based']['altitude']:
                if not re.match(r'^[-+0-9\.]+$', location['coordinate_based']['altitude']):
                    raise ConfigError('Invalid location for interface {0}:\n' \
                                      'altitude should be a positive or negative number'.format(location['name']))

            if location['coordinate_based']['datum']:
                if not re.match(r'^(WGS84|NAD83|MLLW)$', location['coordinate_based']['datum']):
                    raise ConfigError("Invalid location for interface {0}:\n' \
                                      'datum should be WGS84, NAD83, or MLLW".format(location['name']))

        # check elin
        elif location['elin']:
            if not re.match(r'^[0-9]{10,25}$', location['elin']):
                raise ConfigError('Invalid location for interface {0}:\n' \
                                  'ELIN number must be between 10-25 numbers'.format(location['name']))

    # check options
    if lldp['options']['snmp']:
        if not lldp['options']['sys_snmp']:
            raise ConfigError('SNMP must be configured to enable LLDP SNMP')


def generate(lldp):
    # bail out early - looks like removal from running config
    if lldp is None:
        return

    with open('/opt/vyatta/etc/version', 'r') as f:
        tmp = f.read()
        lldp['options']['description'] = tmp.split()[1]


    # generate listen on interfaces
    for intf in lldp['interface_list']:
        tmp = ''
        # add exclamation mark if interface is disabled
        if intf['disable']:
            tmp = '!'

        tmp += intf['name']
        lldp['options']['listen_on'].append(tmp)

    # generate /etc/default/lldpd
    tmpl = jinja2.Template(lldp_tmpl)
    config_text = tmpl.render(lldp['options'])
    with open(config_file, 'w') as f:
        f.write(config_text)

    # generate /etc/lldpd.d/01-vyos.conf
    tmpl = jinja2.Template(vyos_tmpl)
    config_text = tmpl.render(lldp['options'])
    with open(vyos_config_file, 'w') as f:
        f.write(config_text)


def apply(lldp):
    if lldp:
        # start/restart lldp service
        os.system('sudo systemctl restart lldpd.service')
    else:
        # LLDP service has been terminated
        os.system('sudo systemctl stop lldpd.service')
        os.unlink(config_file)


if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        sys.exit(1)

