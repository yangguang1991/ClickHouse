import argparse
import json
import os
from typing import Optional, Union
import digest_helper
from docker_images_helper import get_images_info

DOCKER_DIGEST_LEN = 12
EXCLUDE_FILES = [".md"]


def parse_args(parser) -> argparse.Namespace:
    parser.add_argument(
        "--docker",
        default="",
        required=False,
        help="provide docker image name or all - for all images, or total - for total digest over all images",
    )
    parser.add_argument(
        "--outfile",
        default="",
        type=str,
        required=False,
        help="output file to write result to",
    )
    return parser.parse_args()


class DockerDigester:
    def __init__(self, exclude_files):
        self.images_info = get_images_info()
        assert self.images_info, "Fetch image info error"
        self.exclude_files = exclude_files

    def get_image_digest(self, name) -> str:
        deps = [name]
        digest = None
        while deps:
            dep_name = deps.pop(0)
            digest = digest_helper.digest_path(
                self.images_info[dep_name]["path"],
                digest,
                exclude_files=self.exclude_files,
            )
            deps += self.images_info[dep_name]["deps"]
        return digest.hexdigest()[0:DOCKER_DIGEST_LEN]

    def get_all_digests(self):
        res = {}
        for image_name in self.images_info:
            res[image_name] = self.get_image_digest(image_name)
        return res

    def get_total_digest(self):
        res = []
        for image_name in self.images_info:
            res += [self.get_image_digest(image_name)]
        res.sort()
        res = "-".join(res)
        return digest_helper.digest_string(res)[0:DOCKER_DIGEST_LEN]


if __name__ == "__main__":

    # to be always aligned with docker paths from image.json
    os.chdir(f"{os.path.dirname(__file__)}/../../")

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    args = parse_args(parser)

    res: Optional[Union[str, dict]] = None

    if args.docker:
        docker_digester = DockerDigester(EXCLUDE_FILES)
        if args.docker == "all":
            res = docker_digester.get_all_digests()
        elif args.docker == "total":
            res = docker_digester.get_total_digest()
        else:
            res = docker_digester.get_image_digest(args.docker)
    else:
        print("ERROR: invalid input")
        parser.print_help()
        parser.exit(1)

    if args.outfile and res:
        with open(args.outfile, "w") as file:
            if isinstance(res, str):
                file.write(res)
            elif isinstance(res, dict):
                json.dump(res, file, indent=2)
                file.write('\n')
            else:
                raise AssertionError("Unexpected type for 'res'")
    else:
        if res:
            if isinstance(res, str):
                print(res)
            elif isinstance(res, dict):
                print(json.dumps(res, indent=2))
            else:
                raise AssertionError("Unexpected type for 'res'")
