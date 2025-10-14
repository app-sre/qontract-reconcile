"""
Migration script for External Resources DynamoDB partition key changes.

This script duplicates items in the same table, using state_path format (provision_provider/provisioner_name/provider/identifier)
for the parition key instead of md5 hash
"""

import logging
from typing import Any

import click

from reconcile.cli import (
    config_file,
    dry_run,
)
from reconcile.external_resources.integration import get_aws_api
from reconcile.external_resources.state import DynamoDBStateAdapter
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.external_resources import (
    get_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api_typed.api import AWSApi
from reconcile.utils.runtime.environment import init_env
from reconcile.utils.secret_reader import create_secret_reader

logging.basicConfig(level=logging.INFO)


def create_migrated_item(
    item: dict[str, Any], adapter: DynamoDBStateAdapter
) -> dict[str, Any]:
    """Create a duplicate item with state_path as partition key"""

    er_key_data = item[adapter.ER_KEY]["M"]
    provision_provider = er_key_data[adapter.ER_KEY_PROVISION_PROVIDER]["S"]
    provisioner_name = er_key_data[adapter.ER_KEY_PROVISIONER_NAME]["S"]
    provider = er_key_data[adapter.ER_KEY_PROVIDER]["S"]
    identifier = er_key_data[adapter.ER_KEY_IDENTIFIER]["S"]
    state_path = f"{provision_provider}/{provisioner_name}/{provider}/{identifier}"
    new_item = item.copy()
    new_item[adapter.ER_KEY_HASH] = {"S": state_path}
    return new_item


def scan_and_duplicate_items(
    dynamodb_client: Any, table_name: str, adapter: DynamoDBStateAdapter, dry_run: bool
) -> tuple[int, int]:
    """Scan table and insert duplicated resource states but with state_path keys."""

    paginator = dynamodb_client.get_paginator("scan")
    pages = paginator.paginate(TableName=table_name, PaginationConfig={"PageSize": 100})
    migrated_count = 0
    failed_count = 0
    for page in pages:
        for item in page.get("Items", []):
            old_key = item.get(adapter.ER_KEY_HASH, {}).get("S", "")
            try:
                migrated_item = create_migrated_item(item, adapter)
                if not dry_run:
                    dynamodb_client.put_item(TableName=table_name, Item=migrated_item)
                    logging.info(
                        f"Inserting duplicate resource state: {old_key} -> {migrated_item[adapter.ER_KEY_HASH]}"
                    )
                migrated_count += 1
            except Exception as e:
                logging.error(f"Failed to duplicate item {old_key}: {e}")
                failed_count += 1
    return migrated_count, failed_count


def migrate_table(aws_api: AWSApi, table_name: str, dry_run: bool = False) -> None:
    """Create duplicate items in the same table with state_path partition keys."""

    logging.info(f"Starting migration for table: {table_name}")
    logging.info(f"DRY RUN: {dry_run}")
    dynamodb_client = aws_api.dynamodb.boto3_client
    adapter = DynamoDBStateAdapter()
    table_info = dynamodb_client.describe_table(TableName=table_name)
    item_count = table_info["Table"]["ItemCount"]
    logging.info(f"Table has {item_count} items")

    migrated_count, failed_count = scan_and_duplicate_items(
        dynamodb_client, table_name, adapter, dry_run
    )
    logging.info(
        f"Migration complete. Duplicated: {migrated_count}, Failed: {failed_count}"
    )


@click.command()
@config_file
@dry_run
def main(
    configfile: str,
    dry_run: bool,
) -> None:
    init_env(config_file=configfile)

    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    er_settings = get_settings()

    aws_api = get_aws_api(
        query_func=gql.get_api().query,
        account_name=er_settings.state_dynamodb_account.name,
        region=er_settings.state_dynamodb_region,
        secret_reader=secret_reader,
    )
    migrate_table(
        aws_api=aws_api,
        table_name=er_settings.state_dynamodb_table,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
