#!/usr/bin/env python3
"""Build the BRC IDP PostgreSQL containers."""

import argparse
import logging
import subprocess
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOG = logging.getLogger(__name__)

VERSION = "1.0.0"
PRODUCTS = {
    "loader": {
        "name": "brc-idps-db",
        "components": ("base", "env", "loader"),
    },
    "query": {
        "name": "brc-idps-db-query",
        "components": ("base", "env", "query"),
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true", help="Show build script version")
    parser.add_argument(
        "--product",
        choices=PRODUCTS,
        default="loader",
        help="Container to build (default: loader)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Generate the Dockerfile without building the image",
    )
    parser.add_argument("--no-cache", action="store_true", help="Build without cache")
    parser.add_argument("--push", action="store_true", help="Push the built image")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def create_dockerfile(builddir, product):
    config = PRODUCTS[product]
    dockerfile_dir = builddir / "_dockerfiles"
    dockerfile_dir.mkdir(exist_ok=True)
    dockerfile = dockerfile_dir / f"Dockerfile.{config['name']}"
    with dockerfile.open("w") as output:
        for component in config["components"]:
            output.write((builddir / "recipes" / f"{component}.docker").read_text())
        output.write((builddir / "entrypoints" / f"{product}.entrypoint").read_text())
    return dockerfile


def main():
    args = parse_args()
    if args.debug:
        LOG.setLevel(logging.DEBUG)
    if args.version:
        print(f"v{VERSION}")
        return 0

    config = PRODUCTS[args.product]
    image = f"martincraig/{config['name']}"
    builddir = Path(__file__).resolve().parent
    dockerfile = create_dockerfile(builddir, args.product)
    if args.no_build:
        LOG.info("Generated %s", dockerfile)
        return 0

    command = [
        "docker",
        "buildx",
        "build",
        "--load",
        "-t",
        f"{image}:latest",
        "-f",
        str(dockerfile),
    ]
    if args.no_cache:
        command.append("--no-cache")
    command.append(str(builddir))
    LOG.info("Building %s", image)
    try:
        subprocess.run(command, check=True)
        if args.push:
            subprocess.run(["docker", "push", f"{image}:latest"], check=True)
    except FileNotFoundError:
        LOG.error("Docker was not found; install Docker with Buildx support")
        return 1
    except subprocess.CalledProcessError as exc:
        LOG.error("Command failed with exit status %s", exc.returncode)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
