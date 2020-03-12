"""RQ Dashboard Flask Blueprint.

Uses the standard Flask configuration mechanism e.g. to set the connection
parameters to REDIS. To keep the documentation and defaults all in once place
the default settings must be loaded from ``rq_dashboard.default_settings``
e.g.  as done in ``cli.py``.

RQ Dashboard does not contain any built-in authentication mechanism because

    1. it is the responsbility of the wider hosting app rather than a
       particular blueprint, and

    2. there are numerous ways of adding security orthogonally.

As a quick-and-dirty convenience, the command line invocation in ``cli.py``
provides the option to require HTTP Basic Auth in a few lines of code.

"""
import os
from math import ceil

import arrow
import jinja2
import sanic
import sanic.request
from jinja2 import Environment, FileSystemLoader
from redis_sentinel_url import connect as from_url
from rq import (
    VERSION as rq_version,
    Queue,
    Worker,
    pop_connection,
    push_connection,
    requeue_job,
)
from rq.job import Job
from rq.registry import (
    DeferredJobRegistry,
    FailedJobRegistry,
    FinishedJobRegistry,
    StartedJobRegistry,
)
from sanic import Blueprint
from sanic.response import html as make_response, json
from six import string_types

from .legacy_config import upgrade_config
from .version import VERSION as rq_dashboard_version

CUR_DIR = os.path.abspath(os.path.join(__file__, os.path.pardir))

env = Environment(
    loader=FileSystemLoader(searchpath=[os.path.join(CUR_DIR, 'templates'), os.path.join(CUR_DIR, 'static')]),
    autoescape=jinja2.select_autoescape(['html', 'xml', 'tpl']))

PREFIX = "/rq"


def setup(current_app: sanic.Sanic, prefix=PREFIX):
    while prefix.endswith("/"):
        prefix = prefix.rstrip("/")

    blueprint = Blueprint(
        "rq_dashboard", prefix,
    )

    blueprint.static("/static", os.path.join(CUR_DIR, "static"))
    current_app.static("/favicon.ico", os.path.join(CUR_DIR, "static", "favicon.ico"))

    def render_template(tpl, **kwargs):
        template = env.get_template(tpl)
        return template.render(kwargs,
                               poll_interval=current_app.config.get("RQ_DASHBOARD_POLL_INTERVAL", 2500),
                               url_for=current_app.url_for,
                               rq_url_prefix=prefix + "/",
                               )

    def setup_rq_connection():
        # we need to do It here instead of cli, since It may be embeded
        upgrade_config(current_app)
        # Getting Redis connection parameters for RQ
        redis_url = current_app.config.get("RQ_DASHBOARD_REDIS_URL")
        if isinstance(redis_url, string_types):
            current_app.config["RQ_DASHBOARD_REDIS_URL"] = (redis_url,)
            _, current_app.redis_conn = from_url((redis_url,)[0])
        elif isinstance(redis_url, (tuple, list)):
            _, current_app.redis_conn = from_url(redis_url[0])
        else:
            raise RuntimeError("No Redis configuration!")

    @blueprint.middleware("request")
    async def push_rq_connection(request: sanic.request.Request):
        new_instance_number = request.args.get("instance_number")
        if new_instance_number is not None:
            redis_url = current_app.config.get("RQ_DASHBOARD_REDIS_URL")
            if new_instance_number < len(redis_url):
                _, new_instance = from_url(redis_url[new_instance_number])
            else:
                raise LookupError("Index exceeds RQ list. Not Permitted.")
        else:
            new_instance = current_app.redis_conn
        push_connection(new_instance)
        current_app.redis_conn = new_instance

    @blueprint.middleware("response")
    async def pop_rq_connection(request, response):
        pop_connection()

    def serialize_queues(instance_number, queues):
        return [
            dict(
                name=q.name,
                count=q.count,
                queued_url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=q.name,
                    registry_name="queued",
                    per_page="8",
                    page="1",
                ),
                failed_job_registry_count=FailedJobRegistry(q.name).count,
                failed_url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=q.name,
                    registry_name="failed",
                    per_page="8",
                    page="1",
                ),
                started_job_registry_count=StartedJobRegistry(q.name).count,
                started_url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=q.name,
                    registry_name="started",
                    per_page="8",
                    page="1",
                ),
                deferred_job_registry_count=DeferredJobRegistry(q.name).count,
                deferred_url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=q.name,
                    registry_name="deferred",
                    per_page="8",
                    page="1",
                ),
                finished_job_registry_count=FinishedJobRegistry(q.name).count,
                finished_url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=q.name,
                    registry_name="finished",
                    per_page="8",
                    page="1",
                ),
            )
            for q in queues
        ]

    def serialize_date(dt):
        if dt is None:
            return None
        return arrow.get(dt).to("UTC").datetime.isoformat()

    def serialize_job(job):
        return dict(
            id=job.id,
            created_at=serialize_date(job.created_at),
            ended_at=serialize_date(job.ended_at),
            exc_info=str(job.exc_info) if job.exc_info else None,
            description=job.description,
        )

    def serialize_current_job(job):
        if job is None:
            return "idle"
        return dict(
            job_id=job.id,
            description=job.description,
            created_at=serialize_date(job.created_at),
            call_string=job.get_call_string(),
        )

    def remove_none_values(input_dict):
        return dict(((k, v) for k, v in input_dict.items() if v is not None))

    def pagination_window(total_items, cur_page, per_page, window_size=10):
        all_pages = range(1, int(ceil(total_items / float(per_page))) + 1)
        result = all_pages
        if window_size >= 1:
            temp = min(
                len(all_pages) - window_size, (cur_page - 1) - int(ceil(window_size / 2.0))
            )
            pages_window_start = max(0, temp)
            pages_window_end = pages_window_start + window_size
            result = all_pages[pages_window_start:pages_window_end]
        return result

    def get_queue_registry_jobs_count(queue_name, registry_name, offset, per_page):
        queue = current_queue = Queue(queue_name)
        if registry_name != "queued":
            if per_page >= 0:
                per_page = offset + (per_page - 1)

            if registry_name == "failed":
                current_queue = FailedJobRegistry(queue_name)
            elif registry_name == "deferred":
                current_queue = DeferredJobRegistry(queue_name)
            elif registry_name == "started":
                current_queue = StartedJobRegistry(queue_name)
            elif registry_name == "finished":
                current_queue = FinishedJobRegistry(queue_name)
        else:
            current_queue = queue
        total_items = current_queue.count

        job_ids = current_queue.get_job_ids(offset, per_page)
        current_queue_jobs = [queue.fetch_job(job_id) for job_id in job_ids]
        jobs = [serialize_job(job) for job in current_queue_jobs]

        return (total_items, jobs)

    @blueprint.route("/")
    @blueprint.route("/<instance_number:int>/")
    @blueprint.route("/<instance_number:int>/view")
    @blueprint.route("/<instance_number:int>/view/queues")
    async def queues_overview(request, instance_number=0):

        r = make_response(
            render_template(
                "rq_dashboard/queues.html",
                current_instance=instance_number,
                instance_list=current_app.config.get("RQ_DASHBOARD_REDIS_URL"),
                queues=Queue.all(),
                rq_dashboard_version=rq_dashboard_version,
                rq_version=rq_version,
                active_tab="queues",
                deprecation_options_usage=current_app.config.get(
                    "DEPRECATED_OPTIONS", False
                ),
            ),
            headers={
                "Cache-Control": "no-store"
            }
        )
        return r

    @blueprint.route("/<instance_number:int>/view/workers")
    async def workers_overview(request, instance_number):
        r = make_response(
            render_template(
                "rq_dashboard/workers.html",
                current_instance=instance_number,
                instance_list=current_app.config.get("RQ_DASHBOARD_REDIS_URL"),
                workers=Worker.all(),
                rq_dashboard_version=rq_dashboard_version,
                rq_version=rq_version,
                active_tab="workers",
                deprecation_options_usage=current_app.config.get(
                    "DEPRECATED_OPTIONS", False
                ),
            ),
            headers={
                "Cache-Control": "no-store"
            }
        )
        return r

    @blueprint.route(
        "/<instance_number:int>/view/jobs",
    )
    @blueprint.route(
        "/<instance_number:int>/view/jobs/<queue_name:str>/<registry_name:str>/<per_page:int>/<page:int>"
    )
    async def jobs_overview(request, instance_number, queue_name=None, registry_name="queued", per_page=8, page=1):
        if queue_name is None:
            queue = Queue()
        else:
            queue = Queue(queue_name)
        r = make_response(
            render_template(
                "rq_dashboard/jobs.html",
                current_instance=instance_number,
                instance_list=current_app.config.get("RQ_DASHBOARD_REDIS_URL"),
                queues=Queue.all(),
                queue=queue,
                per_page=per_page,
                page=page,
                registry_name=registry_name,
                rq_dashboard_version=rq_dashboard_version,
                rq_version=rq_version,
                active_tab="jobs",
                deprecation_options_usage=current_app.config.get(
                    "DEPRECATED_OPTIONS", False
                ),
                headers={
                    "Cache-Control": "no-store"
                }
            )
        )
        return r

    @blueprint.route("/<instance_number:int>/view/job/<job_id>")
    async def job_view(request, instance_number, job_id):
        job = Job.fetch(job_id)
        r = make_response(
            render_template(
                "rq_dashboard/job.html",
                current_instance=instance_number,
                instance_list=current_app.config.get("RQ_DASHBOARD_REDIS_URL"),
                id=job.id,
                rq_dashboard_version=rq_dashboard_version,
                rq_version=rq_version,
                deprecation_options_usage=current_app.config.get(
                    "DEPRECATED_OPTIONS", False
                ),
                headers={
                    "Cache-Control": "no-store"
                }
            )
        )
        return r

    @blueprint.route("/job/<job_id:int>/delete", methods=["POST"])
    def delete_job_view(request, job_id):
        job = Job.fetch(job_id)
        job.delete()
        return json(dict(status="OK"))

    @blueprint.route("/job/<job_id>/requeue", methods=["POST"])
    def requeue_job_view(request, job_id):
        requeue_job(job_id, connection=current_app.redis_conn)
        return json(dict(status="OK"))

    @blueprint.route("/requeue/<queue_name>", methods=["GET", "POST"])
    def requeue_all(request, queue_name):
        fq = Queue(queue_name).failed_job_registry
        job_ids = fq.get_job_ids()
        count = len(job_ids)
        for job_id in job_ids:
            requeue_job(job_id, connection=current_app.redis_conn)
        return json(dict(status="OK", count=count))

    @blueprint.route("/queue/<queue_name>/<registry_name>/empty", methods=["POST"])
    def empty_queue(request, queue_name, registry_name):
        if registry_name == "queued":
            q = Queue(queue_name)
            q.empty()
        elif registry_name == "failed":
            ids = FailedJobRegistry(queue_name).get_job_ids()
            for id in ids:
                delete_job_view(id)
        elif registry_name == "deferred":
            ids = DeferredJobRegistry(queue_name).get_job_ids()
            for id in ids:
                delete_job_view(id)
        elif registry_name == "started":
            ids = StartedJobRegistry(queue_name).get_job_ids()
            for id in ids:
                delete_job_view(id)
        elif registry_name == "finished":
            ids = FinishedJobRegistry(queue_name).get_job_ids()
            for id in ids:
                delete_job_view(id)
        return json(dict(status="OK"))

    @blueprint.route("/queue/<queue_name>/compact", methods=["POST"])
    def compact_queue(request, queue_name):
        q = Queue(queue_name)
        q.compact()
        return json(dict(status="OK"))

    @blueprint.route("/<instance_number:int>/data/queues.json")
    def list_queues(request, instance_number):
        queues = serialize_queues(instance_number, sorted(Queue.all()))
        return json(dict(queues=queues))

    @blueprint.route(
        "/<instance_number:int>/data/jobs/<queue_name>/<registry_name>/<per_page:int>/<page:int>.json"
    )
    def list_jobs(request, instance_number, queue_name, registry_name, per_page, page):
        current_page = int(page)
        per_page = int(per_page)
        offset = (current_page - 1) * per_page
        total_items, jobs = get_queue_registry_jobs_count(
            queue_name, registry_name, offset, per_page
        )

        pages_numbers_in_window = pagination_window(total_items, current_page, per_page)
        pages_in_window = [
            dict(
                number=p,
                url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=queue_name,
                    registry_name=registry_name,
                    per_page=per_page,
                    page=p,
                ),
            )
            for p in pages_numbers_in_window
        ]
        last_page = int(ceil(total_items / float(per_page)))

        prev_page = None
        if current_page > 1:
            prev_page = dict(
                url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=queue_name,
                    registry_name=registry_name,
                    per_page=per_page,
                    page=(current_page - 1),
                )
            )

        next_page = None
        if current_page < last_page:
            next_page = dict(
                url=current_app.url_for(
                    "jobs_overview",
                    instance_number=instance_number,
                    queue_name=queue_name,
                    registry_name=registry_name,
                    per_page=per_page,
                    page=(current_page + 1),
                )
            )

        first_page_link = dict(
            url=current_app.url_for(
                "jobs_overview",
                instance_number=instance_number,
                queue_name=queue_name,
                registry_name=registry_name,
                per_page=per_page,
                page=1,
            )
        )
        last_page_link = dict(
            url=current_app.url_for(
                "jobs_overview",
                instance_number=instance_number,
                queue_name=queue_name,
                registry_name=registry_name,
                per_page=per_page,
                page=last_page,
            )
        )

        pagination = remove_none_values(
            dict(
                current_page=current_page,
                num_pages=last_page,
                pages_in_window=pages_in_window,
                next_page=next_page,
                prev_page=prev_page,
                first_page=first_page_link,
                last_page=last_page_link,
            )
        )

        return json(
            dict(
                name=queue_name, registry_name=registry_name, jobs=jobs, pagination=pagination
            )
        )

    @blueprint.route("/<instance_number:int>/data/job/<job_id>.json")
    def job_info(request, instance_number, job_id):
        job = Job.fetch(job_id)
        return json(dict(
            id=job.id,
            created_at=serialize_date(job.created_at),
            enqueued_at=serialize_date(job.enqueued_at),
            ended_at=serialize_date(job.ended_at),
            origin=job.origin,
            status=job.get_status(),
            result=job._result,
            exc_info=str(job.exc_info) if job.exc_info else None,
            description=job.description,
        ))

    @blueprint.route("/<instance_number:int>/data/workers.json")
    def list_workers(request, instance_number):
        def serialize_queue_names(worker):
            return [q.name for q in worker.queues]

        workers = sorted(
            (
                dict(
                    name=worker.name,
                    queues=serialize_queue_names(worker),
                    state=str(worker.get_state()),
                    current_job=serialize_current_job(worker.get_current_job()),
                    version=getattr(worker, "version", ""),
                    python_version=getattr(worker, "python_version", ""),
                )
                for worker in Worker.all()
            ),
            key=lambda w: (w["state"], w["queues"], w["name"]),
        )
        return json(dict(workers=workers))

    setup_rq_connection()

    return blueprint
