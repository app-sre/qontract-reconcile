from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.utils.json import json_dumps

if TYPE_CHECKING:
    from mypy_boto3_cloudformation import CloudFormationClient
    from mypy_boto3_cloudformation.type_defs import (
        ParameterTypeDef,
        StackTypeDef,
        TagTypeDef,
    )


class AWSApiCloudFormation:
    def __init__(self, client: CloudFormationClient) -> None:
        self.client = client

    def create_stack(
        self,
        stack_name: str,
        change_set_name: str,
        template_body: str,
        parameters: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """
        Create a CloudFormation stack using a change set with import existing resources.
        This method creates a change set of type "CREATE" with the provided template and parameters,
        waits for the change set to be created, executes it, and then waits for the stack creation to complete.
        It returns the StackId of the created stack.

        Args:
            stack_name (str): The name of the stack to create.
            change_set_name (str): The name of the change set to create.
            template_body (str): The CloudFormation template body as a string.
            parameters (dict[str, str] | None): A dictionary of parameter key-value pairs for
                the stack. Defaults to None.
            tags (dict[str, str] | None): A dictionary of tag key-value pairs to
                associate with the stack. Defaults to None.

        Returns:
            str: The StackId of the created stack.
        """
        response = self.client.create_change_set(
            StackName=stack_name,
            ChangeSetName=change_set_name,
            TemplateBody=template_body,
            ChangeSetType="CREATE",
            Parameters=self._build_parameters(parameters or {}),
            Tags=self._build_tags(tags or {}),
            ImportExistingResources=True,
        )
        change_set_arn = response["Id"]
        self.client.get_waiter("change_set_create_complete").wait(
            ChangeSetName=change_set_arn
        )
        self.client.execute_change_set(ChangeSetName=change_set_arn)
        self.client.get_waiter("stack_create_complete").wait(StackName=stack_name)
        return response["StackId"]

    def update_stack(
        self,
        stack_name: str,
        template_body: str,
        parameters: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """
        Update a CloudFormation stack with the provided template and parameters.
        This method updates the specified stack, waits for the update to complete,
        and returns the StackId of the updated stack.

        Args:
            stack_name (str): The name of the stack to update.
            template_body (str): The CloudFormation template body as a string.
            parameters (dict[str, str] | None): A dictionary of parameter key-value pairs for
                the stack. Defaults to None.
            tags (dict[str, str] | None): A dictionary of tag key-value pairs to
                associate with the stack. Defaults to None.

        Returns:
            str: The StackId of the updated stack.
        """
        response = self.client.update_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=self._build_parameters(parameters or {}),
            Tags=self._build_tags(tags or {}),
        )
        self.client.get_waiter("stack_update_complete").wait(StackName=stack_name)
        return response["StackId"]

    def get_stack(self, stack_name: str) -> StackTypeDef | None:
        """
        Retrieve information about a CloudFormation stack by its name.
        If the stack exists, it returns the stack details as a dictionary.
        If the stack does not exist, it returns None.

        Args:
            stack_name (str): The name of the stack to retrieve.

        Returns:
            StackTypeDef | None: The stack details if found, otherwise None.
        """
        try:
            response = self.client.describe_stacks(StackName=stack_name)
            return response["Stacks"][0]
        except self.client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ValidationError":
                return None
            raise

    def get_template_body(self, stack_name: str) -> str:
        """
        Retrieve the CloudFormation template body for a specified stack.

        Args:
            stack_name (str): The name of the stack whose template is to be retrieved.

        Returns:
            str: The CloudFormation template body as a string.
        """
        response = self.client.get_template(StackName=stack_name)
        # TemplateBody is str when using yaml
        if isinstance(response["TemplateBody"], str):
            return response["TemplateBody"]
        return json_dumps(response["TemplateBody"])

    @staticmethod
    def _build_parameters(parameters: dict[str, str]) -> list[ParameterTypeDef]:
        return [
            {
                "ParameterKey": key,
                "ParameterValue": value,
            }
            for key, value in sorted(parameters.items())
        ]

    @staticmethod
    def _build_tags(tags: dict[str, str]) -> list[TagTypeDef]:
        return [
            {
                "Key": key,
                "Value": value,
            }
            for key, value in sorted(tags.items())
        ]
