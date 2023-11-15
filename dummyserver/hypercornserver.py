from __future__ import annotations

import concurrent.futures
import contextlib
import functools
import sys
import threading

import hypercorn
import hypercorn.trio
import trio
from quart_trio import QuartTrio


# https://github.com/pgjones/hypercorn/blob/19dfb96411575a6a647cdea63fa581b48ebb9180/src/hypercorn/utils.py#L172-L178
async def graceful_shutdown(shutdown_event: threading.Event) -> None:
    while True:
        if shutdown_event.is_set():
            return
        await trio.sleep(0.1)


async def _start_server(
    config: hypercorn.Config,
    app: QuartTrio,
    ready_event: threading.Event,
    shutdown_event: threading.Event,
) -> None:
    async with trio.open_nursery() as nursery:
        await nursery.start(
            functools.partial(
                hypercorn.trio.serve,
                app,
                config,
                shutdown_trigger=functools.partial(graceful_shutdown, shutdown_event),
            )
        )
        ready_event.set()


@contextlib.contextmanager
def run_hypercorn_in_thread(config: hypercorn.Config, app):
    ready_event = threading.Event()
    shutdown_event = threading.Event()

    with concurrent.futures.ThreadPoolExecutor(
        1, thread_name_prefix="hypercorn dummyserver"
    ) as executor:
        future = executor.submit(
            trio.run,
            _start_server,
            config,
            app,
            ready_event,
            shutdown_event,
        )
        ready_event.wait(5)

        yield

        shutdown_event.set()
        future.result()


def main() -> int:
    # For debugging dummyserver itself - PYTHONPATH=src python -m dummyserver.hypercornserver
    from .handlers import hypercorn_app

    config = hypercorn.Config()
    config.bind = ["localhost:8080"]
    ready_event = threading.Event()
    shutdown_event = threading.Event()
    trio.run(_start_server, config, hypercorn_app, ready_event, shutdown_event)


if __name__ == "__main__":
    sys.exit(main())
