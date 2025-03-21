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

import logging
import os
from datetime import datetime
from shlex import quote

from devlib.utils.android import ApkInfo as _ApkInfo

from wa.framework.configuration import settings
from wa.utils.serializer import read_pod, write_pod, Podable
from wa.utils.types import enum
from wa.utils.misc import atomic_write_path
from typing import Optional, List, Generator, Any, Dict

LogcatLogLevel = enum(['verbose', 'debug', 'info', 'warn', 'error', 'assert'], start=2)

log_level_map: str = ''.join(n[0].upper() for n in LogcatLogLevel.names)

logcat_logger: logging.Logger = logging.getLogger('logcat')
apk_info_cache_logger: logging.Logger = logging.getLogger('apk_info_cache')

apk_info_cache = None


class LogcatEvent(object):
    """
    Represents a Logcat event
    """
    __slots__: List[str] = ['timestamp', 'pid', 'tid', 'level', 'tag', 'message']

    def __init__(self, timestamp: datetime, pid: int, tid: int,
                 level, tag: str, message: str):
        self.timestamp = timestamp
        self.pid = pid
        self.tid = tid
        self.level = level
        self.tag = tag
        self.message = message

    def __repr__(self):
        return '{} {} {} {} {}: {}'.format(
            self.timestamp, self.pid, self.tid,
            self.level.name.upper(), self.tag,
            self.message,
        )

    __str__ = __repr__


class LogcatParser(object):
    """
    Logcat parser
    """
    def parse(self, filepath: str) -> Generator[LogcatEvent, Any, None]:
        """
        parse logcat event file
        """
        with open(filepath, errors='replace') as fh:
            for line in fh:
                event: Optional[LogcatEvent] = self.parse_line(line)
                if event:
                    yield event

    def parse_line(self, line: str) -> Optional[LogcatEvent]:  # pylint: disable=no-self-use
        """
        parse one logcat line
        """
        line = line.strip()
        if not line or line.startswith('-') or ': ' not in line:
            return None

        metadata, message = line.split(': ', 1)

        parts: List[str] = metadata.split(None, 5)
        try:
            ts: str = ' '.join([parts.pop(0), parts.pop(0)])
            timestamp: datetime = datetime.strptime(ts, '%m-%d %H:%M:%S.%f').replace(year=datetime.now().year)
            pid = int(parts.pop(0))
            tid = int(parts.pop(0))
            level = LogcatLogLevel.levels[log_level_map.index(parts.pop(0))]
            tag: str = (parts.pop(0) if parts else '').strip()
        except Exception as e:  # pylint: disable=broad-except
            message = 'Invalid metadata for line:\n\t{}\n\tgot: "{}"'
            logcat_logger.warning(message.format(line, e))
            return None

        return LogcatEvent(timestamp, pid, tid, level, tag, message)


# pylint: disable=protected-access,attribute-defined-outside-init
class ApkInfo(_ApkInfo, Podable):
    '''Implement ApkInfo as a Podable class.'''

    _pod_serialization_version: int = 1

    @staticmethod
    def from_pod(pod: Dict[str, Any]) -> 'ApkInfo':
        """
        create ApkInfo from pod
        """
        instance = ApkInfo()
        instance.path = pod['path']
        instance.package = pod['package']
        instance.activity = pod['activity']
        instance.label = pod['label']
        instance.version_name = pod['version_name']
        instance.version_code = pod['version_code']
        instance.native_code = pod['native_code']
        instance.permissions = pod['permissions']
        instance._apk_path = pod['_apk_path']
        instance._activities = pod['_activities']
        instance._methods = pod['_methods']
        return instance

    def __init__(self, path: Optional[str] = None):
        super().__init__(path)
        self._pod_version = self._pod_serialization_version

    def to_pod(self) -> Dict[str, Any]:
        """
        convert ApkInfo to pod
        """
        pod = super().to_pod()
        pod['path'] = self.path
        pod['package'] = self.package
        pod['activity'] = self.activity
        pod['label'] = self.label
        pod['version_name'] = self.version_name
        pod['version_code'] = self.version_code
        pod['native_code'] = self.native_code
        pod['permissions'] = self.permissions
        pod['_apk_path'] = self._apk_path
        pod['_activities'] = self.activities  # Force extraction
        pod['_methods'] = self.methods  # Force extraction
        return pod

    @staticmethod
    def _pod_upgrade_v1(pod: Dict[str, Any]) -> Dict[str, Any]:
        """
        pod upgrade function version 1
        """
        pod['_pod_version'] = pod.get('_pod_version', 1)
        return pod


class ApkInfoCache:
    """
    cache of Apk info
    """
    @staticmethod
    def _check_env() -> None:
        """
        check environment
        """
        if not os.path.exists(settings.cache_directory):
            os.makedirs(settings.cache_directory)

    def __init__(self, path: str = settings.apk_info_cache_file):
        self._check_env()
        self.path = path
        self.last_modified: Optional[os.stat_result] = None
        self.cache: Dict[str, Dict] = {}
        self._update_cache()

    def store(self, apk_info: ApkInfo, apk_id: str, overwrite: bool = True) -> None:
        """
        store Apk Info into cache
        """
        self._update_cache()
        if apk_id in self.cache and not overwrite:
            raise ValueError('ApkInfo for {} is already in cache.'.format(apk_info.path))
        self.cache[apk_id] = apk_info.to_pod()
        with atomic_write_path(self.path) as at_path:
            write_pod(self.cache, at_path)
        self.last_modified = os.stat(self.path)

    def get_info(self, key: str) -> Optional[ApkInfo]:
        """
        get apk info from cache
        """
        self._update_cache()
        pod = self.cache.get(key)

        info = ApkInfo.from_pod(pod) if pod else None
        return info

    def _update_cache(self) -> None:
        """
        update apk info cache
        """
        if not os.path.exists(self.path):
            return
        if self.last_modified != os.stat(self.path):
            apk_info_cache_logger.debug('Updating cache {}'.format(self.path))
            self.cache = read_pod(self.path)
            self.last_modified = os.stat(self.path)


def get_cacheable_apk_info(path: Optional[str]) -> Optional[ApkInfo]:
    """
    get cacheable apk info
    """
    # pylint: disable=global-statement
    global apk_info_cache
    if not path:
        return None
    stat: os.stat_result = os.stat(path)
    modified: float = stat.st_mtime
    apk_id: str = '{}-{}'.format(path, modified)
    if apk_info_cache:
        info = apk_info_cache.get_info(apk_id)
    else:
        info = None

    if info:
        msg: str = 'Using ApkInfo ({}) from cache'.format(info.package)
    else:
        info = ApkInfo(path)
        if apk_info_cache:
            apk_info_cache.store(info, apk_id, overwrite=True)
            msg = 'Storing ApkInfo ({}) in cache'.format(info.package)
    apk_info_cache_logger.debug(msg)
    return info


apk_info_cache = ApkInfoCache()


def build_apk_launch_command(package: Optional[str], activity: Optional[str] = None,
                             apk_args: Optional[Dict] = None) -> str:
    """
    build apk launch command
    """
    args_string = ''
    if apk_args:
        for k, v in apk_args.items():
            if isinstance(v, str):
                arg = '--es'
                v = quote(v)
            elif isinstance(v, float):
                arg = '--ef'
            elif isinstance(v, bool):
                arg = '--ez'
            elif isinstance(v, int):
                arg = '--ei'
            else:
                raise ValueError('Unable to encode {} {}'.format(v, type(v)))

            args_string = '{} {} {} {}'.format(args_string, arg, k, v)

    if not activity:
        cmd = 'am start -W {} {}'.format(package, args_string)
    else:
        cmd = 'am start -W -n {}/{} {}'.format(package, activity, args_string)

    return cmd
