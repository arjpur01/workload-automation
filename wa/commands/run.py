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


import os
import sys
import shutil

import wa
from wa import Command, settings
from wa.framework import pluginloader
from wa.framework.configuration.parsers import AgendaParser
from wa.framework.execution import Executor
from wa.framework.output import init_run_output, RunOutput
from wa.framework.exception import NotFoundError, ConfigError
from wa.utils import log
from wa.utils.types import toggle_set
from argparse import Namespace
from typing import (Optional, TYPE_CHECKING, cast, List, Dict,
                    Any)
if TYPE_CHECKING:
    from wa.framework.execution import ExecutionContext, ConfigManager
    from wa.framework.pluginloader import __LoaderWrapper
    from wa.framework.configuration.core import RunConfigurationProtocol


class RunCommand(Command):

    name: str = 'run'
    description: str = '''
    Execute automated workloads on a remote device and process the resulting output.

    '''

    def initialize(self, context: Optional['ExecutionContext']) -> None:
        self.parser.add_argument('agenda', metavar='AGENDA',
                                 help="""
                                 Agenda for this workload automation run. This
                                 defines which workloads will be executed, how
                                 many times, with which tunables, etc.  See
                                 example agendas in {} for an example of how
                                 this file should be structured.
                                 """.format(os.path.dirname(wa.__file__)))
        self.parser.add_argument('-d', '--output-directory', metavar='DIR', default=None,
                                 help="""
                                 Specify a directory where the output will be
                                 generated. If the directory already exists,
                                 the script will abort unless -f option (see
                                 below) is used, in which case the contents of
                                 the directory will be overwritten. If this
                                 option is not specified, then {} will be used
                                 instead.
                                 """.format(settings.default_output_directory))
        self.parser.add_argument('-f', '--force', action='store_true',
                                 help="""
                                 Overwrite output directory if it exists. By
                                 default, the script will abort in this
                                 situation to prevent accidental data loss.
                                 """)
        self.parser.add_argument('-i', '--id', action='append', dest='only_run_ids', metavar='ID',
                                 help="""
                                 Specify a workload spec ID from an agenda to
                                 run. If this is specified, only that
                                 particular spec will be run, and other
                                 workloads in the agenda will be ignored. This
                                 option may be used to specify multiple IDs.
                                 """)
        self.parser.add_argument('--disable', action='append', dest='augmentations_to_disable',
                                 default=[],
                                 metavar='INSTRUMENT', help="""
                                 Specify an instrument or output processor to
                                 disable from the command line. This equivalent
                                 to adding "~{metavar}" to the instruments
                                 list in the agenda. This can be used to
                                 temporarily disable a troublesome instrument
                                 for a particular run without introducing
                                 permanent change to the config (which one
                                 might then forget to revert).  This option may
                                 be specified multiple times.
                                 """)

    def execute(self, config: 'ConfigManager', args: Namespace) -> None:  # pylint: disable=arguments-differ
        output: RunOutput = self.set_up_output_directory(config, args)
        log.add_file(output.logfile)
        output.add_artifact('runlog', output.logfile, kind='log',
                            description='Run log.')

        disabled_augmentations = toggle_set([i != '~~' and "~{}".format(i) or i
                                            for i in args.augmentations_to_disable])
        config.jobs_config.disable_augmentations(disabled_augmentations)
        config.jobs_config.only_run_ids(args.only_run_ids)

        parser = AgendaParser()
        if os.path.isfile(args.agenda):
            includes: List[str] = parser.load_from_path(config, args.agenda)
            shutil.copy(args.agenda, output.raw_config_dir)
            for inc in includes:
                shutil.copy(inc, output.raw_config_dir)
        else:
            try:
                cast('__LoaderWrapper', pluginloader).get_plugin_class(args.agenda, kind='workload')
                agenda: Dict[str, List[Dict[str, Any]]] = {'workloads': [{'name': args.agenda}]}
                parser.load(config, agenda, 'CMDLINE_ARGS')
            except NotFoundError:
                msg: str = 'Agenda file "{}" does not exist, and there no workload '\
                    'with that name.\nYou can get a list of available '\
                    'by running "wa list workloads".'
                raise ConfigError(msg.format(args.agenda))

        # Update run info with newly parsed config values
        if output.info:
            output.info.project = cast('RunConfigurationProtocol', config.run_config).project
            output.info.project_stage = cast('RunConfigurationProtocol', config.run_config).project_stage
            output.info.run_name = cast('RunConfigurationProtocol', config.run_config).run_name

        executor = Executor()
        executor.execute(config, output)

    def set_up_output_directory(self, config: 'ConfigManager', args: Namespace) -> RunOutput:
        """
        set up the run output directory
        """
        if args.output_directory:
            output_directory = args.output_directory
        else:
            output_directory = settings.default_output_directory
        self.logger.debug('Using output directory: {}'.format(output_directory))
        try:
            return init_run_output(output_directory, config, args.force)
        except RuntimeError as e:
            if 'path exists' in str(e):
                msg = 'Output directory "{}" exists.\nPlease specify another '\
                      'location, or use -f option to overwrite.'
                self.logger.critical(msg.format(output_directory))
                sys.exit(1)
            else:
                raise e
