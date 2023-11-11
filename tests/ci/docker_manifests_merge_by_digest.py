#!/usr/bin/env python3

import argparse
import json
import logging
import os
import subprocess

import sys
from typing import List, Tuple

from github import Github

from clickhouse_helper import (
    ClickHouseHelper,
    prepare_tests_results_for_clickhouse,
)
from commit_status_helper import format_description, get_commit, post_commit_status
from get_robot_token import get_best_robot_token, get_parameter_from_ssm
from pr_info import PRInfo
from report import TestResult
from s3_helper import S3Helper
from stopwatch import Stopwatch
from upload_result_helper import upload_results
from docker_images_helper import get_images_oredered_list

NAME = "Push multi-arch images to Dockerhub"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="The program gets images from changed_images_*.json, merges images "
        "with different architectures into one manifest and pushes back to docker hub",
    )

    parser.add_argument(
        "--suffix",
        dest="suffixes",
        type=str,
        required=True,
        action="append",
        help="suffixes for existing images' tags. More than two should be given",
    )
    # parser.add_argument(
    #     "--missing-images",
    #     type=str,
    #     required=True,
    #     help="json string or json file with images to build {IMAGE: DIGEST} or type all to build all",
    # )
    parser.add_argument(
        "--digests",
        type=str,
        required=True,
        help="json string or json file with images and their digests {IMAGE: DIGEST}",
    )
    parser.add_argument(
        "--tag",
        type=str,
        required=True,
        help="Tag that should be applied for multiarch images",
    )
    parser.add_argument("--reports", default=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-reports",
        action="store_false",
        dest="reports",
        default=argparse.SUPPRESS,
        help="don't push reports to S3 and github",
    )
    parser.add_argument("--push", default=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-push-images",
        action="store_false",
        dest="push",
        default=argparse.SUPPRESS,
        help="don't push images to docker hub",
    )

    args = parser.parse_args()
    if len(args.suffixes) < 2:
        parser.error("more than two --suffix should be given")

    return args


def create_manifest(image: str, tags: List[str], push: bool) -> Tuple[str, str]:
    tag = tags[0]
    manifest = f"{image}:{tag}"
    cmd = "docker manifest create --amend " + " ".join((f"{image}:{t}" for t in tags))
    logging.info("running: %s", cmd)
    with subprocess.Popen(
        cmd,
        shell=True,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    ) as popen:
        retcode = popen.wait()
        if retcode != 0:
            output = popen.stdout.read()  # type: ignore
            logging.error("failed to create manifest for %s:\n %s\n", manifest, output)
            return manifest, "FAIL"
        if not push:
            return manifest, "OK"

    cmd = f"docker manifest push {manifest}"
    logging.info("running: %s", cmd)
    with subprocess.Popen(
        cmd,
        shell=True,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    ) as popen:
        retcode = popen.wait()
        if retcode != 0:
            output = popen.stdout.read()  # type: ignore
            logging.error("failed to push %s:\n %s\n", manifest, output)
            return manifest, "FAIL"

    return manifest, "OK"


def main():
    # to be always aligned with docker paths from image.json
    os.chdir(f"{os.path.dirname(__file__)}/../../")
    logging.basicConfig(level=logging.INFO)
    stopwatch = Stopwatch()

    args = parse_args()

    if args.push:
        subprocess.check_output(  # pylint: disable=unexpected-keyword-arg
            "docker login --username 'robotclickhouse' --password-stdin",
            input=get_parameter_from_ssm("dockerhub_robot_password"),
            encoding="utf-8",
            shell=True,
        )

    archs = args.suffixes
    assert len(archs) > 1, "arch suffix input param is invalid"
    assert len(args.tag) > 6, "invalid tag"

    image_digests = (
        json.loads(args.digests)
        if not os.path.isfile(args.digests)
        else json.load(open(args.digests))
    )
    # missing_images = (
    #     image_digests
    #     if args.missing_images == "all"
    #     else json.loads(args.missing_images)
    #     if not os.path.isfile(args.missing_images)
    #     else json.load(open(args.missing_images))
    # )

    test_results = []
    status = "success"

    ok_cnt, fail_cnt = 0, 0
    images = get_images_oredered_list()
    for image_obj in images:
        tag = image_digests[image_obj.repo]
        result_tag = args.tag
        # if image_obj.repo not in missing_images:
        #     continue
        if image_obj.only_amd64:
            # FIXME: WA until full arm support
            tags = [result_tag] + [
                f"{tag}-{arch}" for arch in archs if arch != "aarch64"
            ]
        else:
            tags = [result_tag] + [f"{tag}-{arch}" for arch in archs]
        manifest, test_result = create_manifest(image_obj.repo, tags, args.push)
        test_results.append(TestResult(manifest, test_result))
        if test_result != "OK":
            status = "failure"
            fail_cnt += 1
        else:
            ok_cnt += 1

    pr_info = PRInfo()
    s3_helper = S3Helper()

    url = upload_results(s3_helper, pr_info.number, pr_info.sha, test_results, [], NAME)

    print(f"::notice ::Report url: {url}")

    if not args.reports:
        return

    description = format_description(
        f"Multiarch images created [ok: {ok_cnt}, failed: {fail_cnt}]"
    )

    gh = Github(get_best_robot_token(), per_page=100)
    commit = get_commit(gh, pr_info.sha)
    post_commit_status(commit, status, url, description, NAME, pr_info)

    prepared_events = prepare_tests_results_for_clickhouse(
        pr_info,
        test_results,
        status,
        stopwatch.duration_seconds,
        stopwatch.start_time_str,
        url,
        NAME,
    )
    ch_helper = ClickHouseHelper()
    ch_helper.insert_events_into(db="default", table="checks", events=prepared_events)
    if status == "failure":
        sys.exit(1)


if __name__ == "__main__":
    main()
