import argparse
import sys
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkswr.v2.region.swr_region import SwrRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkswr.v2 import *
import yaml
import logging


def get_logger(level=logging.INFO):
    # 创建logger实例
    logger = logging.getLogger("LLM-Benchmark")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        # 创建格式化器
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        console_handler.setFormatter(formatter)
        # 添加处理器到logger
        logger.addHandler(console_handler)

    return logger


logger = get_logger(logging.INFO)


def load_config(config_file):
    logger.debug(f"Loading config file: {config_file}")
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
            return config
    except Exception as e:
        logger.error("Failed to load config file: %s", e)
        return None


def get_swr_client(config):
    credentials = BasicCredentials(config["ak"], config["sk"])

    return SwrClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(SwrRegion.value_of(config["region"])) \
        .build()


def get_repo_list(client, config):
    logger.info("Getting repo list need to update...")
    try:
        request = ListReposDetailsRequest()
        filter = []
        if config.get("namespace"):
            filter.append(f"namespace::{config['namespace']}")
            # request.namespace = config["namespace"]
        if config.get("limit"):
            filter.append(f"limit::{config['limit']}")
            # request.limit = config["limit"]
        if config.get("is_public"):
            filter.append(f"is_public::{config.get('is_public', 'false')}")
        request.filter = "|".join(filter)
        logger.debug(f"Get repo list request: {request}")
        response = client.list_repos_details(request)
        logger.debug("Get repo list response: %s", response)
        if response.body is None:
            return []
        repo_list = [repo.name for repo in response.body]
        return repo_list
    except exceptions.ClientRequestException as e:
        logger.error("Error occurred while fetching repository list: %s", e)
        return None


def update_repo_attr(client, config, repo_list):
    if len(repo_list) < 1:
        logger.info("No repositories to update.")
        return

    logger.info("Updating repository attribute...")
    try:
        request = UpdateRepoRequest()
        request.namespace = config["namespace"]
        total_num = len(repo_list)
        is_public = True if config["target_attr"] == "public" else False
        for i, repo in enumerate(repo_list, 1):
            logger.info(f"Updating repo: [{i}/{total_num}] {repo}")
            request.repository = repo.replace('/', '$')
            request.body = UpdateRepoRequestBody(
                is_public=is_public
            )
            logger.debug(f"Update repo request: {request}")
            client.update_repo(request)
        logger.info("Repository attribute update completed.")
    except exceptions.ClientRequestException as e:
        logger.error("Error occurred while updating repository attribute: %s", e)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="SWR Repo Attribute Update")
    argparser.add_argument("-c","--config", type=str, default="config.yaml", help="config file")
    args = argparser.parse_args()

    cfg = load_config(args.config)
    logger.debug(f"Config: {cfg}")

    client = get_swr_client(cfg)
    repo_list = get_repo_list(client, cfg)
    logger.debug(f"Repo List: {repo_list}")
    update_repo_attr(client, cfg, repo_list)

