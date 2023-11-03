import argparse
import concurrent.futures
import json
import subprocess
from typing import Optional
from docker_images_helper import get_images_info


def run_docker_command(image: str, image_digest: str, arch: Optional[str] = None):
    command = [
        "docker",
        "manifest",
        "inspect",
        f"{image}:{image_digest}" if not arch else f"{image}:{image_digest}-{arch}",
    ]

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False
    )

    return {
        "image": image,
        "image_digest": image_digest,
        "arch": arch,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "return_code": process.returncode,
    }


def parse_args(parser) -> argparse.Namespace:
    parser.add_argument(
        "--infile",
        default="",
        type=str,
        required=True,
        help="input json file with image data, format {IMAGE: DIGEST}",
    )
    parser.add_argument(
        "--outfile",
        default="",
        type=str,
        required=False,
        help="otput file to write json result to",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="check missing docker images, without arch input multiarch image will be checked",
    )
    parser.add_argument(
        "--aarch64",
        action="store_true",
        help="check missing aarch64 docker images",
    )
    parser.add_argument(
        "--amd64",
        action="store_true",
        help="check missing amd64 docker images",
    )
    return parser.parse_args()


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    args = parse_args(parser)
    with open(args.infile, "r") as file:
        images = json.load(file)

    images_info = get_images_info()

    if not args.docker:
        print("ERROR: only docker option supported atm")
        parser.print_help()
        parser.exit(1)

    arch = None
    if args.aarch64 and not args.amd64:
        arch = "aarch64"
    elif not args.aarch64 and args.amd64:
        arch = "amd64"
    elif not args.aarch64 and not args.amd64:
        pass  # check for multiarch manifest
    else:
        print("ERROR: invalid input")
        parser.print_help()
        parser.exit(1)

    image_names, image_digests = [], []
    for name, digest in images.items():
        if arch == "aarch64" and images_info[name]["only_amd64"]:
            # FIXME: WA until full arm support
            continue
        image_names += [name]
        image_digests += [digest]

    result = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(run_docker_command, image, image_digest, arch)
            for image, image_digest in zip(image_names, image_digests)
        ]

        responses = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]
        for resp in responses:
            name, stdout, stderr, digest, arch = (
                resp["image"],
                resp["stdout"],
                resp["stderr"],
                resp["image_digest"],
                resp["arch"],
            )
            if stderr:
                if stderr.startswith("no such manifest"):
                    result[name] = digest
                else:
                    print(f"Eror: Unknown error: {stderr}, {name}, {arch}")
            elif stdout:
                if "manifests" in stdout:
                    pass
                else:
                    print(f"Eror: Unknown response: {stdout}")
            else:
                print(f"Eror: No response for {name}, {digest}, {arch}")

    if args.outfile:
        with open(args.outfile, "w") as file:
            json.dump(result, file, indent=2)
            file.write('\n')
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
