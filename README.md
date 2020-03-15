Introduction
============

`rq-dashboard` is a general purpose, lightweight,
[Sanic](https://github.com/huge-success/sanic)-based web front-end to monitor your
[RQ](http://python-rq.org/) queues, jobs, and workers in realtime.

[![Build
Status](https://travis-ci.org/Parallels/rq-dashboard.svg?branch=master)](https://travis-ci.org/Parallels/rq-dashboard)
[![Python
Support](https://img.shields.io/pypi/pyversions/rq-dashboard.svg)](https://pypi.python.org/pypi/rq-dashboard)
![PyPI Downloads](https://img.shields.io/pypi/dw/rq-dashboard)

Maturity notes
--------------

The RQ dashboard is currently being developed and is in beta stage.

Installing with Docker
----------------------

**Currently the Docker installation is broken !! To be fixed soon!!**
You can also run the dashboard inside of docker:

``` {.console}
$ docker pull eoranged/rq-dashboard
$ docker run -p 9181:9181 eoranged/rq-dashboard
```

and you can then run the image. You can pass additional options using
environment variables with prefix `RQ_DASHBOARD_*`:

    - RQ_DASHBOARD_REDIS_URL=redis://<redis:6379>
    - RQ_DASHBOARD_USERNAME=rq
    - RQ_DASHBOARD_PASSWORD=password

See more info on how to pass environment variables in [Docker documentation](https://docs.docker.com/engine/reference/commandline/run/#set-environment-variables--e---env---env-file)

Installing from PyPI
--------------------

``` {.console}
$ pipenv install git+https://github.com/4thel00z/rq-dashboard#egg=rq-dashboard
```

Running the dashboard
---------------------

Run the dashboard standalone, like this:

``` {.console}
#eventually
$ pipenv shell

$ rq-dashboard
* Running on http://127.0.0.1:9181/
...
```

``` {.console}
$ rq-dashboard --help
Usage: rq-dashboard [OPTIONS]

  Run the RQ Dashboard Flask server.

  All configuration can be set on the command line or through environment
  variables of the form RQ_DASHBOARD_*. For example RQ_DASHBOARD_USERNAME.

  A subset of the configuration (the configuration parameters used by the
  underlying sanic blueprint) can also be provided in a Python module
  referenced using --config, or with a .cfg file referenced by the
  RQ_DASHBOARD_SETTINGS environment variable.

Options:
  -b, --bind TEXT                 IP or hostname on which to bind HTTP server
  -p, --port INTEGER              Port on which to bind HTTP server
  --url-prefix TEXT               URL prefix e.g. for use behind a reverse
                                  proxy
  --username TEXT                 HTTP Basic Auth username (not used if not
                                  set)
  --password TEXT                 HTTP Basic Auth password
  -c, --config TEXT               Configuration file (Python module on search
                                  path)
  -u, --redis-url TEXT            Redis URL. Can be specified multiple times.
                                  Default: redis://127.0.0.1:6379
  --poll-interval, --interval INTEGER
                                  Refresh interval in ms
  --extra-path TEXT               Append specified directories to sys.path
  --debug / --normal              Enter DEBUG mode
  -v, --verbose                   Enable verbose logging
  --help                          Show this message and exit.
```

Integrating the dashboard in your Flask app
-------------------------------------------

The dashboard can be integrated in to your own [Flask](http://flask.pocoo.org/) app by accessing the blueprint directly in the normal way, e.g.:

``` {.python}
from sanic import Sanic 
import rq_dashboard

app = Sanic(__name__)
prefix = "/rq"
blueprint_namespace="rq_dashboard"
username="some_username"
password="some_password"

bp = rq_dashboard.setup(app, prefix, blueprint_namespace, username, password)
app.blueprint(bp)

@app.route("/")
async def hello():
    return "Hello World!"

if __name__ == "__main__":
    app.run()
```

If you start the Sanic app on the default port, you can access the
dashboard at <http://localhost:5000/rq>. The `cli.py:main` entry point
provides a simple working example.

Developing
----------

Develop in a virtualenv and make sure you have all the necessary build
time (and run time) dependencies with

    $ pipenv install

Develop in the normal way with

    $ python setup.py develop

Stats
-----

-   [PyPI stats](https://pypistats.org/packages/rq-dashboard)
-   [Github stats](https://github.com/Parallels/rq-dashboard/graphs/traffic)
