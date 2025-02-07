# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

from hashlib import md5
from os import makedirs
from os.path import isdir, isfile, join

from platformio.compat import WINDOWS, hashlib_encode_data

# Windows CLI has limit with command length to 8192
# Leave 2000 chars for flags and other options
MAX_SOURCES_LENGTH = 6000


def long_sources_hook(env, sources):
    _sources = str(sources).replace("\\", "/")
    if len(_sources) < MAX_SOURCES_LENGTH:
        return sources

    # fix space in paths
    data = []
    for line in _sources.split(".o "):
        line = line.strip()
        if not line.endswith(".o"):
            line += ".o"
        data.append(f'"{line}"')

    return f'@"{_file_long_data(env, " ".join(data))}"'


def long_incflags_hook(env, incflags):
    _incflags = env.subst(incflags).replace("\\", "/")
    if len(_incflags) < MAX_SOURCES_LENGTH:
        return incflags

    # fix space in paths
    data = []
    for line in _incflags.split(" -I"):
        line = line.strip()
        if not line.startswith("-I"):
            line = f"-I{line}"
        data.append(f'-I"{line[2:]}"')

    return f'@"{_file_long_data(env, " ".join(data))}"'


def _file_long_data(env, data):
    build_dir = env.subst("$BUILD_DIR")
    if not isdir(build_dir):
        makedirs(build_dir)
    tmp_file = join(
        build_dir, f"longcmd-{md5(hashlib_encode_data(data)).hexdigest()}"
    )
    if isfile(tmp_file):
        return tmp_file
    with open(tmp_file, "w") as fp:
        fp.write(data)
    return tmp_file


def exists(_):
    return True


def generate(env):
    if not WINDOWS:
        return None

    env.Replace(_long_sources_hook=long_sources_hook)
    env.Replace(_long_incflags_hook=long_incflags_hook)
    coms = {
        key: env.get(key, "").replace(
            "$SOURCES", "${_long_sources_hook(__env__, SOURCES)}"
        )
        for key in ("ARCOM", "LINKCOM")
    }
    for key in ("_CCCOMCOM", "ASPPCOM"):
        coms[key] = env.get(key, "").replace(
            "$_CPPINCFLAGS", "${_long_incflags_hook(__env__, _CPPINCFLAGS)}")
    env.Replace(**coms)

    return env
