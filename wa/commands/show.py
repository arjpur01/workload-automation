#    Copyright 2014-2018 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# TODO: because of some weirdness involving get_params_rst and underline
#       functions from wa.utils.doc, pylint gets stuck here for a very
#       long time. To avoid that, skip this file.
# pylint: disable-all

import sys
from subprocess import call, Popen, PIPE

from devlib.utils.misc import escape_double_quotes

from wa import Command
from wa.framework import pluginloader
from wa.framework.configuration.core import MetaConfiguration, RunConfiguration
from wa.framework.exception import NotFoundError
from wa.framework.target.descriptor import list_target_descriptions, TargetDescriptionProtocol
from wa.utils.types import caseless_string, identifier
from wa.utils.doc import (strip_inlined_text, get_rst_from_plugin,
                          get_params_rst, underline)
from wa.utils.misc import which
from typing import TYPE_CHECKING, cast, Optional, List, Type
from argparse import Namespace
if TYPE_CHECKING:
    from wa.framework.execution import ExecutionContext, ConfigManager
    from wa.framework.pluginloader import __LoaderWrapper
    from wa.framework.plugin import Plugin
    from wa.framework.configuration.core import ConfigurationPoint


class ShowCommand(Command):

    name: str = 'show'
    description: str = 'Display documentation for the specified plugin (workload, instrument, etc.).'

    def initialize(self, context: Optional['ExecutionContext']) -> None:
        self.parser.add_argument('plugin', metavar='PLUGIN',
                                 help='The name of the plugin to display documentation for.')

    def execute(self, state: 'ConfigManager', args: Namespace) -> None:
        name: str = identifier(args.plugin)
        rst_output: Optional[str] = None

        if name == caseless_string('settings'):
            rst_output = get_rst_for_global_config()
            rst_output += get_rst_for_envars()
            plugin_name: str = name.lower()
            kind: str = 'global:'
        else:
            try:
                plugin: Optional[Type['Plugin']] = cast('__LoaderWrapper', pluginloader).get_plugin_class(name)
            except NotFoundError:
                plugin = None
            if plugin:
                rst_output = get_rst_from_plugin(plugin)
                plugin_name = plugin.name or ''
                kind = '{}:'.format(plugin.kind)
            else:
                target: Optional[TargetDescriptionProtocol] = get_target_description(name)
                if target:
                    rst_output = get_rst_from_target(target)
                    plugin_name = target.name
                    kind = 'target:'

        if not rst_output:
            raise NotFoundError('Could not find plugin or alias "{}"'.format(name))

        if which('pandoc'):
            p = Popen(['pandoc', '-f', 'rst', '-t', 'man'], stdin=PIPE, stdout=PIPE, stderr=PIPE)
            output_, _ = p.communicate(rst_output.encode(sys.stdin.encoding))
            output = output_.decode(sys.stdout.encoding)

            # Make sure to double escape back slashes
            output = output.replace('\\', '\\\\\\')

            # Correctly format the title and page number of the man page
            title, body = output.split('\n', 1)
            title = '.TH {}{} 7'.format(kind, plugin_name)
            output = '\n'.join([title, body])

            call('echo "{}" | man -l -'.format(escape_double_quotes(output)), shell=True)
        else:
            print(rst_output)  # pylint: disable=superfluous-parens


def get_target_description(name: str) -> Optional[TargetDescriptionProtocol]:
    """
    get target description
    """
    targets = list_target_descriptions()
    for target in targets:
        if name == identifier(target.name):
            return target
    return None


def get_rst_from_target(target: TargetDescriptionProtocol) -> str:
    """
    get restructured text from target description
    """
    text: str = underline(target.name, '~')
    if hasattr(target, 'description'):
        desc: str = strip_inlined_text(target.description or '')
        text += desc
    text += underline('Device Parameters:', '-')
    text += get_params_rst(target.conn_params)
    text += get_params_rst(target.platform_params)
    text += get_params_rst(target.target_params)
    text += get_params_rst(target.assistant_params)
    text += '.. Note: For available runtime parameters please see the documentation'
    return text + '\n'


def get_rst_for_global_config() -> str:
    """
    get restructured text for global configuration
    """
    text: str = underline('Global Configuration')
    text += 'These parameters control the behaviour of WA/run as a whole, they ' \
            'should be set inside a config file (either located in ' \
            '$WA_USER_DIRECTORY/config.yaml or one which is specified with -c), ' \
            'or into config/global section of the agenda.\n\n'

    cfg_points: List['ConfigurationPoint'] = MetaConfiguration.config_points + RunConfiguration.config_points
    text += get_params_rst(cfg_points)
    return text


def get_rst_for_envars() -> str:
    """
    get restructured text for environment variables
    """
    text = underline('Environment Variables')
    text += '''WA_USER_DIRECTORY: str
    This is the location WA will look for config.yaml, plugins,  dependencies,
    and it will also be used for local caches, etc. If this variable is not set,
    the default location is ``~/.workload_automation`` (this is created when WA
    is installed).

    .. note.. This location must be writable by the user who runs WA.'''
    return text
