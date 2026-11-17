"""Acquire process ownership before importing modules that touch user data."""

import argparse
import os
import sys
import traceback


def launch():
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="StreamCap")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "6006")))
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.web = args.web or os.getenv("PLATFORM") == "web"
    instance = None
    job = None
    try:
        if sys.platform == "win32":
            from windows_runtime import ProcessJob, SingleInstance

            instance = SingleInstance()
            if not instance.acquired:
                instance.activate_existing()
                return 0
            job = ProcessJob()
            instance.publish("web" if args.web else "desktop", f"http://{args.host}:{args.port}" if args.web else None)

        from application import run_application

        run_application(args, instance)
        return 0
    except Exception:
        details = traceback.format_exc()
        if sys.stderr is not None:
            print(details, file=sys.stderr)
        if sys.platform == "win32":
            from windows_runtime import notify, runtime_directory

            directory = runtime_directory()
            directory.mkdir(parents=True, exist_ok=True)
            log = directory / "startup-error.log"
            log.write_text(details, encoding="utf-8")
            if not args.smoke_test:
                notify(f"StreamCap 启动失败 / failed to start.\n\n{log}\n\n{details.splitlines()[-1]}", error=True)
        return 1
    finally:
        if instance is not None:
            instance.close()
        # Keep the Job Object handle alive until the OS tears down this process.
        _ = job
