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

import sys
from fnmatch import fnmatch
from os import getcwd
from os.path import join

import click
from serial.tools import miniterm

from platformio import exception, util
from platformio.compat import dump_json_to_unicode
from platformio.project.config import ProjectConfig


@click.group(short_help="Monitor device or list existing")
def cli():
    pass


@cli.command("list", short_help="List devices")
@click.option("--serial", is_flag=True, help="List serial ports, default")
@click.option("--logical", is_flag=True, help="List logical devices")
@click.option("--mdns", is_flag=True, help="List multicast DNS services")
@click.option("--json-output", is_flag=True)
def device_list(  # pylint: disable=too-many-branches
        serial, logical, mdns, json_output):
    if not logical and not mdns:
        serial = True
    data = {}
    if serial:
        data['serial'] = util.get_serial_ports()
    if logical:
        data['logical'] = util.get_logical_devices()
    if mdns:
        data['mdns'] = util.get_mdns_services()

    single_key = list(data)[0] if len(list(data)) == 1 else None

    if json_output:
        return click.echo(
            dump_json_to_unicode(data[single_key] if single_key else data))

    titles = {
        "serial": "Serial Ports",
        "logical": "Logical Devices",
        "mdns": "Multicast DNS Services"
    }

    for key, value in data.items():
        if not single_key:
            click.secho(titles[key], bold=True)
            click.echo("=" * len(titles[key]))

        if key == "serial":
            for item in value:
                click.secho(item['port'], fg="cyan")
                click.echo("-" * len(item['port']))
                click.echo(f"Hardware ID: {item['hwid']}")
                click.echo(f"Description: {item['description']}")
                click.echo("")

        if key == "logical":
            for item in value:
                click.secho(item['path'], fg="cyan")
                click.echo("-" * len(item['path']))
                click.echo(f"Name: {item['name']}")
                click.echo("")

        if key == "mdns":
            for item in value:
                click.secho(item['name'], fg="cyan")
                click.echo("-" * len(item['name']))
                click.echo(f"Type: {item['type']}")
                click.echo(f"IP: {item['ip']}")
                click.echo(f"Port: {item['port']}")
                if item['properties']:
                    click.echo(
                        (
                            "Properties: %s"
                            % "; ".join(
                                [
                                    f"{k}={v}"
                                    for k, v in item['properties'].items()
                                ]
                            )
                        )
                    )
                click.echo("")

        if single_key:
            click.echo("")

    return True


@cli.command("monitor", short_help="Monitor device (Serial)")
@click.option("--port", "-p", help="Port, a number or a device name")
@click.option("--baud", "-b", type=int, help="Set baud rate, default=9600")
@click.option("--parity",
              default="N",
              type=click.Choice(["N", "E", "O", "S", "M"]),
              help="Set parity, default=N")
@click.option("--rtscts",
              is_flag=True,
              help="Enable RTS/CTS flow control, default=Off")
@click.option("--xonxoff",
              is_flag=True,
              help="Enable software flow control, default=Off")
@click.option("--rts",
              default=None,
              type=click.IntRange(0, 1),
              help="Set initial RTS line state")
@click.option("--dtr",
              default=None,
              type=click.IntRange(0, 1),
              help="Set initial DTR line state")
@click.option("--echo", is_flag=True, help="Enable local echo, default=Off")
@click.option("--encoding",
              default="UTF-8",
              help="Set the encoding for the serial port (e.g. hexlify, "
              "Latin1, UTF-8), default: UTF-8")
@click.option("--filter", "-f", multiple=True, help="Add text transformation")
@click.option("--eol",
              default="CRLF",
              type=click.Choice(["CR", "LF", "CRLF"]),
              help="End of line mode, default=CRLF")
@click.option("--raw",
              is_flag=True,
              help="Do not apply any encodings/transformations")
@click.option("--exit-char",
              type=int,
              default=3,
              help="ASCII code of special character that is used to exit "
              "the application, default=3 (Ctrl+C)")
@click.option("--menu-char",
              type=int,
              default=20,
              help="ASCII code of special character that is used to "
              "control miniterm (menu), default=20 (DEC)")
@click.option("--quiet",
              is_flag=True,
              help="Diagnostics: suppress non-error messages, default=Off")
@click.option("-d",
              "--project-dir",
              default=getcwd,
              type=click.Path(exists=True,
                              file_okay=False,
                              dir_okay=True,
                              resolve_path=True))
@click.option(
    "-e",
    "--environment",
    help="Load configuration from `platformio.ini` and specified environment")
def device_monitor(**kwargs):  # pylint: disable=too-many-branches
    env_options = {}
    try:
        env_options = get_project_options(kwargs['project_dir'],
                                          kwargs['environment'])
        for k in ("port", "speed", "rts", "dtr"):
            k2 = f"monitor_{k}"
            if k == "speed":
                k = "baud"
            if kwargs[k] is None and k2 in env_options:
                kwargs[k] = env_options[k2]
                if k != "port":
                    kwargs[k] = int(kwargs[k])
    except exception.NotPlatformIOProject:
        pass

    if not kwargs['port']:
        ports = util.get_serial_ports(filter_hwid=True)
        if len(ports) == 1:
            kwargs['port'] = ports[0]['port']

    sys.argv = ["monitor"] + env_options.get("monitor_flags", [])
    for k, v in kwargs.items():
        if k in ("port", "baud", "rts", "dtr", "environment", "project_dir"):
            continue
        k = "--" + k.replace("_", "-")
        if k in env_options.get("monitor_flags", []):
            continue
        if isinstance(v, bool):
            if v:
                sys.argv.append(k)
        elif isinstance(v, tuple):
            for i in v:
                sys.argv.extend([k, i])
        else:
            sys.argv.extend([k, str(v)])

    if kwargs['port'] and {"*", "?", "[", "]"} & set(kwargs['port']):
        for item in util.get_serial_ports():
            if fnmatch(item['port'], kwargs['port']):
                kwargs['port'] = item['port']
                break

    try:
        miniterm.main(default_port=kwargs['port'],
                      default_baudrate=kwargs['baud'] or 9600,
                      default_rts=kwargs['rts'],
                      default_dtr=kwargs['dtr'])
    except Exception as e:
        raise exception.MinitermException(e)


def get_project_options(project_dir, environment=None):
    config = ProjectConfig.get_instance(join(project_dir, "platformio.ini"))
    config.validate(envs=[environment] if environment else None)
    if not environment:
        if default_envs := config.default_envs():
            environment = default_envs[0]
        else:
            environment = config.envs()[0]
    return config.items(env=environment, as_dict=True)
