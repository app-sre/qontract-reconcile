import logging
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable, Mapping
from enum import Enum
from itertools import chain
from typing import (
    Any,
)

from pydantic import BaseModel

from reconcile.gql_definitions.slo_documents.slo_documents import SLODocumentV1
from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
from reconcile.typed_queries.slo_documents import get_slo_documents
from reconcile.typed_queries.status_board import (
    get_selected_app_data,
    get_status_board,
)
from reconcile.utils.differ import diff_mappings
from reconcile.utils.ocm.status_board import (
    ApplicationOCMSpec,
    BaseOCMSpec,
    ServiceMetadataSpec,
    ServiceOCMSpec,
    create_application,
    create_product,
    create_service,
    delete_application,
    delete_product,
    delete_service,
    get_application_services,
    get_managed_products,
    get_product_applications,
    update_application,
    update_service,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import QontractReconcileIntegration

QONTRACT_INTEGRATION = "status-board-exporter"


class Action(Enum):
    create = "create"
    update = "update"
    delete = "delete"


class AbstractStatusBoard(ABC, BaseModel):
    """Abstract class for upgrade policies
    Used to create and delete upgrade policies in OCM."""

    id: str | None
    name: str
    fullname: str
    metadata: dict[str, Any] | ServiceMetadataSpec | None

    @abstractmethod
    def create(self, ocm: OCMBaseClient) -> None:
        pass

    @abstractmethod
    def update(self, ocm: OCMBaseClient) -> None:
        pass

    @abstractmethod
    def delete(self, ocm: OCMBaseClient) -> None:
        pass

    @abstractmethod
    def summarize(self) -> str:
        pass

    @staticmethod
    @abstractmethod
    def get_priority() -> int:
        pass

    @abstractmethod
    def to_ocm_spec(self) -> BaseOCMSpec:
        pass

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AbstractStatusBoard):
            return NotImplemented
        return self.name == other.name and self.fullname == other.fullname


class Product(AbstractStatusBoard):
    applications: list["Application"] | None

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.to_ocm_spec()
        self.id = create_product(ocm, spec)

    def update(self, ocm: OCMBaseClient) -> None:
        err_msg = "Called update on StatusBoardHandler that doesn't have update method"
        logging.error(err_msg)
        raise UpdateNotSupportedError(err_msg)

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Product "{self.name}" without id')
            return
        delete_product(ocm, self.id)

    def summarize(self) -> str:
        return f'Product: "{self.name}"'

    def to_ocm_spec(self) -> BaseOCMSpec:
        return {
            "name": self.name,
            "fullname": self.fullname,
        }

    @staticmethod
    def get_priority() -> int:
        return 0


class Application(AbstractStatusBoard):
    product: Product
    services: list["Service"] | None
    metadata: dict[str, Any]

    def create(self, ocm: OCMBaseClient) -> None:
        if self.product.id:
            spec = self.to_ocm_spec()
            self.id = create_application(ocm, spec)
        else:
            logging.warning("Missing product id for application")

    def update(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to update Application "{self.name}" without id')
            return
        spec = self.to_ocm_spec()
        update_application(ocm, self.id, spec)

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Application "{self.name}" without id')
            return
        delete_application(ocm, self.id)

    def summarize(self) -> str:
        return f'Application: "{self.name}" "{self.fullname}"'

    def to_ocm_spec(self) -> ApplicationOCMSpec:
        product_id = self.product.id or ""
        return {
            "name": self.name,
            "fullname": self.fullname,
            "metadata": self.metadata,
            "product": {"id": product_id},
        }

    @staticmethod
    def get_priority() -> int:
        return 1


class Service(AbstractStatusBoard):
    application: Application
    metadata: ServiceMetadataSpec

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.to_ocm_spec()
        if self.application.id:
            self.id = create_service(ocm, spec)
        else:
            logging.warning("Missing application id for service")

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Service "{self.name}" without id')
            return
        delete_service(ocm, self.id)

    def update(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to update Service "{self.name}" without id')
            return
        spec = self.to_ocm_spec()
        if self.application.id:
            update_service(ocm, self.id, spec)
        else:
            logging.warning("Missing application id for service")

    def summarize(self) -> str:
        return f'Service: "{self.name}" "{self.fullname}"'

    def to_ocm_spec(self) -> ServiceOCMSpec:
        application_id = self.application.id or ""

        return {
            "name": self.name,
            "fullname": self.fullname,
            "metadata": self.metadata,
            "status_type": "traffic_light",
            "service_endpoint": "none",
            "application": {"id": application_id},
        }

    @staticmethod
    def get_priority() -> int:
        return 2

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Service):
            return NotImplemented
        return (
            self.name == other.name
            and self.fullname == other.fullname
            and self.metadata == other.metadata
        )


# Resolve forward references after class definitions
Product.update_forward_refs()
Application.update_forward_refs()
Service.update_forward_refs()


class UpdateNotSupportedError(Exception):
    pass


class StatusBoardHandler(BaseModel):
    action: Action
    status_board_object: AbstractStatusBoard

    def act(self, dry_run: bool, ocm: OCMBaseClient) -> None:
        logging.info(f"{self.action} - {self.status_board_object.summarize()}")

        if dry_run:
            return

        match self.action:
            case Action.delete:
                self.status_board_object.delete(ocm)
            case Action.create:
                self.status_board_object.create(ocm)
            case Action.update:
                self.status_board_object.update(ocm)


class StatusBoardExporterIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_product_apps(
        sb: StatusBoardV1,
    ) -> dict[str, dict[str, dict[str, dict[str, set[str]]]]]:
        global_selectors = (
            sb.global_app_selectors.exclude or [] if sb.global_app_selectors else []
        )
        return {
            p.product_environment.product.name: get_selected_app_data(
                global_selectors, p
            )
            for p in sb.products
        }

    @staticmethod
    def get_current_products_applications_services(
        ocm_api: OCMBaseClient,
    ) -> list[Product]:
        products_raw = get_managed_products(ocm_api)
        products = [Product(**p) for p in products_raw]

        for p in products:
            if not p.id:
                logging.error(f'Product "{p.name}" has no id')
                continue
            p.applications = [
                Application(**a, product=p)
                for a in get_product_applications(ocm_api, p.id)
            ]
            for a in p.applications:
                if not a.id:
                    logging.error(f'Application "{a.name}" has no id')
                    continue
                a.services = [
                    Service(**s, application=a)
                    for s in get_application_services(ocm_api, a.id)
                ]

        return products

    @staticmethod
    def desired_abstract_status_board_map(
        desired_product_apps: Mapping[str, dict[str, dict[str, dict[str, set[str]]]]],
        slodocs: list[SLODocumentV1],
    ) -> dict[str, AbstractStatusBoard]:
        """
        Returns a Mapping of all the AbstractStatusBoard data objects as dictionaries.
        The key is formed by combining the Product, Application and Service name
        separeted by a '/' character. This is the same format as the fullname property
        on Status Board OCM API.
        """
        desired_abstract_status_board_map: dict[str, AbstractStatusBoard] = {}
        for product_name, apps in desired_product_apps.items():
            product = Product(
                id=None,
                name=product_name,
                fullname=product_name,
                applications=[],
                metadata={},
            )
            desired_abstract_status_board_map[product_name] = product
            for a in apps:
                key = f"{product_name}/{a}"
                desired_abstract_status_board_map[key] = Application(
                    id=None,
                    name=a,
                    fullname=key,
                    services=[],
                    product=product,
                    metadata=apps[a]["metadata"],
                )
        for slodoc in slodocs:
            products = [
                ns.namespace.environment.product.name for ns in slodoc.namespaces
            ]
            for slo in slodoc.slos or []:
                for product_name in products:
                    if slodoc.app.parent_app:
                        app = f"{slodoc.app.parent_app.name}-{slodoc.app.name}"
                    else:
                        app = slodoc.app.name

                    # Check if the product or app is excluded from the desired list
                    product_or_app_excluded = (
                        product_name not in desired_product_apps
                        or app not in desired_product_apps.get(product_name, set())
                    )

                    # Check if statusBoard label exists and is explicitly disabled
                    status_board_enabled = (
                        slodoc.labels is not None
                        and "statusBoard" in slodoc.labels
                        and slodoc.labels["statusBoard"] == "enabled"
                    )

                    if product_or_app_excluded or not status_board_enabled:
                        continue

                    key = f"{product_name}/{app}/{slo.name}"
                    metadata: ServiceMetadataSpec = {
                        "sli_type": slo.sli_type,
                        "sli_specification": slo.sli_specification,
                        "slo_details": slo.slo_details,
                        "target": slo.slo_target,
                        "target_unit": slo.slo_target_unit,
                        "window": slo.slo_parameters.window,
                    }
                    desired_abstract_status_board_map[key] = Service(
                        id=None,
                        name=slo.name,
                        fullname=key,
                        metadata=metadata,
                        application=desired_abstract_status_board_map[
                            f"{product_name}/{app}"
                        ],
                    )

        return desired_abstract_status_board_map

    @staticmethod
    def current_abstract_status_board_map(
        current_products_applications_services: Iterable[Product],
    ) -> dict[str, AbstractStatusBoard]:
        return_value: dict[str, AbstractStatusBoard] = {}
        for product in current_products_applications_services:
            return_value[product.name] = product
            for app in product.applications or []:
                return_value[f"{product.name}/{app.name}"] = app
                for service in app.services or []:
                    return_value[f"{product.name}/{app.name}/{service.name}"] = service

        return return_value

    @staticmethod
    def _compare_metadata(
        current_metadata: dict[str, Any] | ServiceMetadataSpec,
        desired_metadata: dict[str, Any] | ServiceMetadataSpec,
    ) -> bool:
        """
        Compare metadata dictionaries with deep equality checking for nested structures.

        :param current_metadata: The current metadata dictionary
        :param desired_metadata: The desired metadata dictionary
        :return: True if metadata are equal, False otherwise
        """
        # Convert TypedDict to regular dict to allow variable key access
        current_dict = dict(current_metadata)
        desired_dict = dict(desired_metadata)

        if current_dict.keys() != desired_dict.keys():
            return False

        for key, current_value in current_dict.items():
            desired_value = desired_dict[key]

            # Handle None values
            if current_value is None or desired_value is None:
                if current_value is not desired_value:
                    return False
                continue

            # Handle sets
            if isinstance(current_value, set) and isinstance(desired_value, set):
                if current_value != desired_value:
                    return False
            # Handle lists and tuples
            elif isinstance(current_value, (list, tuple)) and isinstance(
                desired_value, (list, tuple)
            ):
                if len(current_value) != len(desired_value):
                    return False

                try:
                    sorted_current = sorted(current_value, key=repr)
                    sorted_desired = sorted(desired_value, key=repr)
                except Exception:
                    # Fallback: compare without sorting
                    sorted_current = list(current_value)
                    sorted_desired = list(desired_value)

                for c, d in zip(sorted_current, sorted_desired, strict=True):
                    if isinstance(c, dict) and isinstance(d, dict):
                        if not StatusBoardExporterIntegration._compare_metadata(c, d):
                            return False
                    elif isinstance(c, (list, tuple)) and isinstance(d, (list, tuple)):
                        if not StatusBoardExporterIntegration._compare_metadata(
                            {"x": c}, {"x": d}
                        ):
                            return False
                    elif c != d:
                        return False
            # Handle nested dictionaries
            elif isinstance(current_value, dict) and isinstance(desired_value, dict):
                if not StatusBoardExporterIntegration._compare_metadata(
                    current_value, desired_value
                ):
                    return False
            # Handle primitive types
            elif current_value != desired_value:
                return False

        return True

    @staticmethod
    def _status_board_objects_equal(
        current: AbstractStatusBoard, desired: AbstractStatusBoard
    ) -> bool:
        """
        Check if two AbstractStatusBoard objects are equal, including metadata comparison.

        :param current: The current AbstractStatusBoard object
        :param desired: The desired AbstractStatusBoard object
        :return: True if objects are equal, False otherwise
        """
        # Check basic equality first (name, fullname)
        if current.name != desired.name or current.fullname != desired.fullname:
            return False

        # Compare metadata with deep equality
        if current.metadata and desired.metadata:
            return StatusBoardExporterIntegration._compare_metadata(
                current.metadata, desired.metadata
            )
        else:
            return True

    @staticmethod
    def get_diff(
        desired_abstract_status_board_map: Mapping[str, AbstractStatusBoard],
        current_abstract_status_board_map: Mapping[str, AbstractStatusBoard],
    ) -> list[StatusBoardHandler]:
        return_list: list[StatusBoardHandler] = []

        diff_result = diff_mappings(
            current_abstract_status_board_map,
            desired_abstract_status_board_map,
            equal=StatusBoardExporterIntegration._status_board_objects_equal,
        )

        for pair in chain(diff_result.identical.values(), diff_result.change.values()):
            pair.desired.id = pair.current.id

        return_list.extend(
            StatusBoardHandler(action=Action.create, status_board_object=o)
            for o in diff_result.add.values()
        )

        return_list.extend(
            StatusBoardHandler(action=Action.delete, status_board_object=o)
            for o in diff_result.delete.values()
        )

        # Handle Applications that need updates (metadata changes)
        applications_to_update = [
            a.desired
            for _, a in diff_result.change.items()
            if isinstance(a.desired, Application)
        ]

        return_list.extend(
            StatusBoardHandler(action=Action.update, status_board_object=a)
            for a in applications_to_update
        )

        services_to_update = [
            s.desired
            for _, s in diff_result.change.items()
            if isinstance(s.desired, Service)
        ]

        return_list.extend(
            StatusBoardHandler(action=Action.update, status_board_object=s)
            for s in services_to_update
        )

        return return_list

    @staticmethod
    def apply_diff(
        dry_run: bool, ocm_api: OCMBaseClient, diff: list[StatusBoardHandler]
    ) -> None:
        creations: list[StatusBoardHandler] = []
        deletions: list[StatusBoardHandler] = []
        updates: list[StatusBoardHandler] = []

        for o in diff:
            match o.action:
                case Action.create:
                    creations.append(o)
                case Action.delete:
                    deletions.append(o)
                case Action.update:
                    updates.append(o)

        # Products need to be created before Applications
        # Applications need to be created before Services
        creations.sort(key=lambda x: x.status_board_object.get_priority())

        # Services need to be deleted before Applications
        # Applications need to be deleted before Products
        deletions.sort(key=lambda x: x.status_board_object.get_priority(), reverse=True)

        for d in creations + deletions + updates:
            d.act(dry_run, ocm_api)

    def run(self, dry_run: bool) -> None:
        slodocs = get_slo_documents()
        for sb in get_status_board():
            ocm_api = init_ocm_base_client(sb.ocm, self.secret_reader)

            # Desired state
            desired_product_apps: dict[
                str, dict[str, dict[str, dict[str, set[str]]]]
            ] = self.get_product_apps(sb)
            desired_abstract_status_board_map = self.desired_abstract_status_board_map(
                desired_product_apps, slodocs
            )

            # Current state
            current_products_applications_services = (
                self.get_current_products_applications_services(ocm_api)
            )
            current_abstract_status_board_map = self.current_abstract_status_board_map(
                current_products_applications_services
            )
            diff = self.get_diff(
                desired_abstract_status_board_map,
                current_abstract_status_board_map,
            )

            self.apply_diff(dry_run, ocm_api, diff)
