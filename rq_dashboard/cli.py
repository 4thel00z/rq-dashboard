import importlib
import logging
import os
import sys

import click
import sanic
import sanic.log
import sanic.request

from .version import VERSION
from .web import setup, PREFIX


def make_sanic_app(config,
                   username,
                   password,
                   prefix=PREFIX,
                   blueprint_namespace="rq_dashboard",
                   redis_url='redis://127.0.0.1:6379'):
    """Return Sanic app with default configuration and registered blueprint."""
    app = sanic.Sanic(__name__)

    # Used in testing
    if redis_url:
        app.config['RQ_DASHBOARD_REDIS_URL'] = 'redis://127.0.0.1:6379'

    # Override with any settings in config file, if given.
    if config:
        app.config.from_object(importlib.import_module(config))

    # Override from a configuration file in the env variable, if present.
    if "RQ_DASHBOARD_SETTINGS" in os.environ:
        app.config.from_envvar("RQ_DASHBOARD_SETTINGS")

    # Optionally add basic auth to blueprint and register with app.
    blueprint = setup(app, prefix, blueprint_namespace, username, password)
    app.blueprint(blueprint)
    return app


@click.command()
@click.option(
    "-b",
    "--bind",
    default="0.0.0.0",
    help="IP or hostname on which to bind HTTP server",
)
@click.option(
    "-p", "--port", default=9181, type=int, help="Port on which to bind HTTP server"
)
@click.option(
    "--url-prefix", default="", help="URL prefix e.g. for use behind a reverse proxy"
)
@click.option(
    "--username", default=None, help="HTTP Basic Auth username (not used if not set)"
)
@click.option("--password", default=None, help="HTTP Basic Auth password")
@click.option(
    "-c",
    "--config",
    default=None,
    help="Configuration file (Python module on search path)",
)
@click.option(
    "-u",
    "--redis-url",
    default=None,
    multiple=True,
    help="Redis URL. Can be specified multiple times. Default: redis://127.0.0.1:6379",
)
@click.option(
    "--poll-interval",
    "--interval",
    "poll_interval",
    default=None,
    type=int,
    help="Refresh interval in ms",
)
@click.option(
    "--extra-path",
    default=".",
    multiple=True,
    help="Append specified directories to sys.path",
)
@click.option("--debug/--normal", default=False, help="Enter DEBUG mode")
@click.option(
    "-v", "--verbose", is_flag=True, default=False, help="Enable verbose logging"
)
def run(
        bind,
        port,
        url_prefix,
        username,
        password,
        config,
        redis_url,
        poll_interval,
        extra_path,
        debug,
        verbose,
):
    """Run the RQ Dashboard Sanic server.

    All configuration can be set on the command line or through environment
    variables of the form RQ_DASHBOARD_*. For example RQ_DASHBOARD_USERNAME.

    A subset of the configuration (the configuration parameters used by the
    underlying flask blueprint) can also be provided in a Python module
    referenced using --config, or with a .cfg file referenced by the
    RQ_DASHBOARD_SETTINGS environment variable.

    """
    if extra_path:
        sys.path += list(extra_path)

    click.echo("RQ Dashboard version {}".format(VERSION))
    app = make_sanic_app(config, username, password, url_prefix)

    if redis_url:
        app.config["RQ_DASHBOARD_REDIS_URL"] = redis_url
    else:
        app.config["RQ_DASHBOARD_REDIS_URL"] = "redis://127.0.0.1:6379"
    if poll_interval:
        app.config["RQ_DASHBOARD_POLL_INTERVAL"] = poll_interval

    log = sanic.log.logger
    if verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)
        log.error(" * Running on {}:{}".format(bind, port))
    for name in app.router.routes_names:
        log.debug(name)
    app.run(host=bind, port=port, debug=debug)


def main():
    run(auto_envvar_prefix="RQ_DASHBOARD")
