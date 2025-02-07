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

import os
import sys
from os.path import basename, dirname, isdir, join, realpath

from SCons import Builder, Util  # pylint: disable=import-error
from SCons.Script import COMMAND_LINE_TARGETS  # pylint: disable=import-error
from SCons.Script import AlwaysBuild  # pylint: disable=import-error
from SCons.Script import DefaultEnvironment  # pylint: disable=import-error
from SCons.Script import Export  # pylint: disable=import-error
from SCons.Script import SConscript  # pylint: disable=import-error

from platformio import fs
from platformio.compat import string_types
from platformio.util import pioversion_to_intstr

SRC_HEADER_EXT = ["h", "hpp"]
SRC_C_EXT = ["c", "cc", "cpp"]
SRC_BUILD_EXT = SRC_C_EXT + ["S", "spp", "SPP", "sx", "s", "asm", "ASM"]
SRC_FILTER_DEFAULT = ["+<*>", f"-<.git{os.sep}>", f"-<.svn{os.sep}>"]


def scons_patched_match_splitext(path, suffixes=None):
    """Patch SCons Builder, append $OBJSUFFIX to the end of each target"""
    tokens = Util.splitext(path)
    if suffixes and tokens[1] and tokens[1] in suffixes:
        return (path, tokens[1])
    return tokens


def _build_project_deps(env):
    project_lib_builder = env.ConfigureProjectLibBuilder()

    # prepend project libs to the beginning of list
    env.Prepend(LIBS=project_lib_builder.build())
    # prepend extra linker related options from libs
    env.PrependUnique(
        **{
            key: project_lib_builder.env.get(key)
            for key in ("LIBS", "LIBPATH", "LINKFLAGS")
            if project_lib_builder.env.get(key)
        })

    projenv = env.Clone()

    # CPPPATH from dependencies
    projenv.PrependUnique(CPPPATH=project_lib_builder.env.get("CPPPATH"))
    # extra build flags from `platformio.ini`
    projenv.ProcessFlags(env.get("SRC_BUILD_FLAGS"))

    is_test = "__test" in COMMAND_LINE_TARGETS
    if is_test:
        projenv.BuildSources("$BUILDTEST_DIR", "$PROJECTTEST_DIR",
                             "$PIOTEST_SRC_FILTER")
    if not is_test or env.GetProjectOption("test_build_project_src", False):
        projenv.BuildSources("$BUILDSRC_DIR", "$PROJECTSRC_DIR",
                             env.get("SRC_FILTER"))

    if not env.get("PIOBUILDFILES") and not COMMAND_LINE_TARGETS:
        sys.stderr.write(
            "Error: Nothing to build. Please put your source code files "
            "to '%s' folder\n" % env.subst("$PROJECTSRC_DIR"))
        env.Exit(1)

    Export("projenv")


def BuildProgram(env):

    def _append_pio_macros():
        env.AppendUnique(CPPDEFINES=[(
            "PLATFORMIO",
            int("{0:02d}{1:02d}{2:02d}".format(*pioversion_to_intstr())))])

    _append_pio_macros()

    env.PrintConfiguration()

    # fix ASM handling under non case-sensitive OS
    if not Util.case_sensitive_suffixes(".s", ".S"):
        env.Replace(AS="$CC", ASCOM="$ASPPCOM")

    if ("debug" in COMMAND_LINE_TARGETS
            or env.GetProjectOption("build_type") == "debug"):
        env.ProcessDebug()

    # process extra flags from board
    if "BOARD" in env and "build.extra_flags" in env.BoardConfig():
        env.ProcessFlags(env.BoardConfig().get("build.extra_flags"))

    # apply user flags
    env.ProcessFlags(env.get("BUILD_FLAGS"))

    # process framework scripts
    env.BuildFrameworks(env.get("PIOFRAMEWORK"))

    # restore PIO macros if it was deleted by framework
    _append_pio_macros()

    # remove specified flags
    env.ProcessUnFlags(env.get("BUILD_UNFLAGS"))

    if "__test" in COMMAND_LINE_TARGETS:
        env.ProcessTest()

    # build project with dependencies
    _build_project_deps(env)

    # append into the beginning a main LD script
    if env.get("LDSCRIPT_PATH") and all(
        "-Wl,-T" not in f for f in env['LINKFLAGS']
    ):
        env.Prepend(LINKFLAGS=["-T", "$LDSCRIPT_PATH"])

    # enable "cyclic reference" for linker
    if env.get("LIBS") and env.GetCompilerType() == "gcc":
        env.Prepend(_LIBFLAGS="-Wl,--start-group ")
        env.Append(_LIBFLAGS=" -Wl,--end-group")

    program = env.Program(join("$BUILD_DIR", env.subst("$PROGNAME")),
                          env['PIOBUILDFILES'])
    env.Replace(PIOMAINPROG=program)

    AlwaysBuild(
        env.Alias(
            "checkprogsize", program,
            env.VerboseAction(env.CheckUploadSize,
                              "Checking size $PIOMAINPROG")))

    return program


def ParseFlagsExtended(env, flags):  # pylint: disable=too-many-branches
    if not isinstance(flags, list):
        flags = [flags]
    result = {}
    for raw in flags:
        for key, value in env.ParseFlags(str(raw)).items():
            if key not in result:
                result[key] = []
            result[key].extend(value)

    cppdefines = []
    for item in result['CPPDEFINES']:
        if not Util.is_Sequence(item):
            cppdefines.append(item)
            continue
        name, value = item[:2]
        if '\"' in value:
            value = value.replace('\"', '\\\"')
        elif value.isdigit():
            value = int(value)
        elif value.replace(".", "", 1).isdigit():
            value = float(value)
        cppdefines.append((name, value))
    result['CPPDEFINES'] = cppdefines

    # fix relative CPPPATH & LIBPATH
    for k in ("CPPPATH", "LIBPATH"):
        for i, p in enumerate(result.get(k, [])):
            if isdir(p):
                result[k][i] = realpath(p)

    # fix relative path for "-include"
    for i, f in enumerate(result.get("CCFLAGS", [])):
        if isinstance(f, tuple) and f[0] == "-include":
            result['CCFLAGS'][i] = (f[0], env.File(realpath(f[1].get_path())))

    return result


def ProcessFlags(env, flags):  # pylint: disable=too-many-branches
    if not flags:
        return
    env.Append(**env.ParseFlagsExtended(flags))

    if undefines := [
        u
        for u in env.get("CCFLAGS", [])
        if isinstance(u, string_types) and u.startswith("-U")
    ]:
        for undef in undefines:
            env['CCFLAGS'].remove(undef)
            if undef[2:] in env['CPPDEFINES']:
                env['CPPDEFINES'].remove(undef[2:])
        env.Append(_CPPDEFFLAGS=f' {" ".join(undefines)}')


def ProcessUnFlags(env, flags):
    if not flags:
        return
    parsed = env.ParseFlagsExtended(flags)

    # get all flags and copy them to each "*FLAGS" variable
    all_flags = []
    for key, unflags in parsed.items():
        if key.endswith("FLAGS"):
            all_flags.extend(unflags)
    for key, unflags in parsed.items():
        if key.endswith("FLAGS"):
            parsed[key].extend(all_flags)

    for key, unflags in parsed.items():
        for unflag in unflags:
            for current in env.get(key, []):
                conditions = [
                    unflag == current,
                    isinstance(current, (tuple, list))
                    and unflag[0] == current[0]
                ]
                if any(conditions):
                    env[key].remove(current)


def MatchSourceFiles(env, src_dir, src_filter=None):
    src_filter = env.subst(src_filter) if src_filter else None
    src_filter = src_filter or SRC_FILTER_DEFAULT
    return fs.match_src_files(env.subst(src_dir), src_filter,
                              SRC_BUILD_EXT + SRC_HEADER_EXT)


def CollectBuildFiles(env,
                      variant_dir,
                      src_dir,
                      src_filter=None,
                      duplicate=False):
    sources = []
    variants = []

    src_dir = env.subst(src_dir)
    if src_dir.endswith(os.sep):
        src_dir = src_dir[:-1]

    for item in env.MatchSourceFiles(src_dir, src_filter):
        _reldir = dirname(item)
        _src_dir = join(src_dir, _reldir) if _reldir else src_dir
        _var_dir = join(variant_dir, _reldir) if _reldir else variant_dir

        if _var_dir not in variants:
            variants.append(_var_dir)
            env.VariantDir(_var_dir, _src_dir, duplicate)

        if fs.path_endswith_ext(item, SRC_BUILD_EXT):
            sources.append(env.File(join(_var_dir, basename(item))))

    return sources


def BuildFrameworks(env, frameworks):
    if not frameworks:
        return

    if "BOARD" not in env:
        sys.stderr.write("Please specify `board` in `platformio.ini` to use "
                         "with '%s' framework\n" % ", ".join(frameworks))
        env.Exit(1)

    board_frameworks = env.BoardConfig().get("frameworks", [])
    if frameworks == ["platformio"]:
        if board_frameworks:
            frameworks.insert(0, board_frameworks[0])
        else:
            sys.stderr.write(
                "Error: Please specify `board` in `platformio.ini`\n")
            env.Exit(1)

    for f in frameworks:
        if f == "arduino":
            # Arduino IDE appends .o the end of filename
            Builder.match_splitext = scons_patched_match_splitext
            if "nobuild" not in COMMAND_LINE_TARGETS:
                env.ConvertInoToCpp()

        if f in board_frameworks:
            SConscript(env.GetFrameworkScript(f), exports="env")
        else:
            sys.stderr.write(
                "Error: This board doesn't support %s framework!\n" % f)
            env.Exit(1)


def BuildLibrary(env, variant_dir, src_dir, src_filter=None):
    env.ProcessUnFlags(env.get("BUILD_UNFLAGS"))
    return env.StaticLibrary(
        env.subst(variant_dir),
        env.CollectBuildFiles(variant_dir, src_dir, src_filter))


def BuildSources(env, variant_dir, src_dir, src_filter=None):
    nodes = env.CollectBuildFiles(variant_dir, src_dir, src_filter)
    DefaultEnvironment().Append(
        PIOBUILDFILES=[env.Object(node) for node in nodes])


def exists(_):
    return True


def generate(env):
    env.AddMethod(BuildProgram)
    env.AddMethod(ParseFlagsExtended)
    env.AddMethod(ProcessFlags)
    env.AddMethod(ProcessUnFlags)
    env.AddMethod(MatchSourceFiles)
    env.AddMethod(CollectBuildFiles)
    env.AddMethod(BuildFrameworks)
    env.AddMethod(BuildLibrary)
    env.AddMethod(BuildSources)
    return env
