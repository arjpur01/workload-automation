#    Copyright 2018 ARM Limited
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

from wa.framework.configuration.core import MetaConfiguration, RunConfiguration
from wa.framework.configuration.plugin_cache import PluginCache
from wa.utils.serializer import yaml
from wa.utils.doc import strip_inlined_text
from typing import List, TYPE_CHECKING, TextIO, Optional, cast
if TYPE_CHECKING:
    from wa.framework.configuration.core import ConfigurationPoint

DEFAULT_AUGMENTATIONS: List[str] = [
    'execution_time',
    'interrupts',
    'cpufreq',
    'status',
    'csv',
]


def _format_yaml_comment(param: 'ConfigurationPoint', short_description=False) -> str:
    """
    format yaml comment
    """
    comment: Optional[str] = param.description
    comment = strip_inlined_text(comment or '')
    if short_description:
        comment = comment.split('\n\n')[0] if comment else ''
    comment = comment.replace('\n', '\n# ') if comment else ''
    comment = "# {}\n".format(comment)
    return comment


def _format_augmentations(output: TextIO) -> None:
    """
    format augmentations
    """
    plugin_cache = PluginCache()
    output.write("augmentations:\n")
    for plugin in DEFAULT_AUGMENTATIONS:
        plugin_cls = plugin_cache.loader.get_plugin_class(plugin)
        output.writelines(_format_yaml_comment(cast('ConfigurationPoint', plugin_cls), short_description=True))
        output.write(" - {}\n".format(plugin))
        output.write("\n")


def generate_default_config(path: str) -> None:
    """
    generate default configuration
    """
    with open(path, 'w') as output:
        for param in MetaConfiguration.config_points + RunConfiguration.config_points:
            entry = {param.name: param.default}
            write_param_yaml(entry, param, output)
        _format_augmentations(output)


def write_param_yaml(entry, param: 'ConfigurationPoint', output: TextIO) -> None:
    """
    write the configuration parameter into yaml file
    """
    comment: str = _format_yaml_comment(param)
    output.writelines(comment)
    yaml.dump(entry, output, default_flow_style=False)
    output.write("\n")
