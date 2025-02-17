import logging
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import (
    Any,
    Optional,
)

from pydantic import BaseModel

from reconcile.gql_definitions.slo_documents.slo_documents import SLODocumentV1
from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
from reconcile.typed_queries.slo_documents import get_slo_documents
from reconcile.typed_queries.status_board import (
    get_selected_app_names,
    get_status_board,
)
from reconcile.utils.differ import diff_mappings
from reconcile.utils.ocm.status_board import (
    create_application,
    create_product,
    delete_application,
    delete_product,
    get_application_services,
    get_managed_products,
    get_product_applications,
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
    metadata: dict[str, Any] | None

    @abstractmethod
    def create(self, ocm: OCMBaseClient) -> None:
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


class Product(AbstractStatusBoard):
    applications: list["Application"] | None

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.dict(by_alias=True)
        spec.pop("applications")
        spec.pop("id")
        self.id = create_product(ocm, spec)

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Product "{self.name}" without id')
            return
        delete_product(ocm, self.id)

    def summarize(self) -> str:
        return f'Product: "{self.name}"'

    @staticmethod
    def get_priority() -> int:
        return 0


class Application(AbstractStatusBoard):
    product: Optional["Product"]
    services: list["Service"] | None

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.dict(by_alias=True)
        spec.pop("id")
        product = spec.pop("product")
        product_id = product.get("id")
        if product_id:
            spec["product"] = {"id": product_id}
            self.id = create_application(ocm, spec)
        else:
            logging.warning("Missing product id for application")

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Application "{self.name}" without id')
            return
        delete_application(ocm, self.id)

    def summarize(self) -> str:
        return f'Application: "{self.name}" "{self.fullname}"'

    @staticmethod
    def get_priority() -> int:
        return 1


class Service(AbstractStatusBoard):
    application: Optional["Application"]

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.dict(by_alias=True)
        spec.pop("id")
        application = spec.pop("application")
        application_id = application.get("id")
        if application_id:
            spec["application"] = {"id": application_id}
            # TODO: Implement create_service
            # self.id = create_application(ocm, spec)
        else:
            logging.warning("Missing product id for application")

    def delete(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to delete Application "{self.name}" without id')
            return
        # TODO: Implement delete_service
        # delete_application(ocm, self.id)

    def summarize(self) -> str:
        return f'Service: "{self.name}" "{self.fullname}"'

    @staticmethod
    def get_priority() -> int:
        return 2


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


class StatusBoardExporterIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_product_apps(sb: StatusBoardV1) -> dict[str, set[str]]:
        global_selectors = (
            sb.global_app_selectors.exclude or [] if sb.global_app_selectors else []
        )
        return {
            p.product_environment.product.name: get_selected_app_names(
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
                Application(**a) for a in get_product_applications(ocm_api, p.id)
            ]
            for a in p.applications:
                if not a.id:
                    logging.error(f'Application "{a.name}" has no id')
                    continue
                a.services = [
                    Service(**s) for s in get_application_services(ocm_api, a.id)
                ]

        return products

    @staticmethod
    def desired_abstract_status_board_map(
        desired_product_apps: Mapping[str, set[str]], slodocs: list[SLODocumentV1]
    ) -> Mapping[str, dict[str, Any]]:
        desired_abstract_status_board_map: dict[str, dict[str, Any]] = {}
        for product, apps in desired_product_apps.items():
            desired_abstract_status_board_map[product] = {
                "type": "product",
                "product": product,
                "app": "",
            }
            for a in apps:
                desired_abstract_status_board_map[f"{product}/{a}"] = {
                    "type": "app",
                    "product": product,
                    "app": a,
                }
        for slodoc in slodocs:
            products = [
                ns.namespace.environment.product.name for ns in slodoc.namespaces
            ]
            for slo in slodoc.slos or []:
                for product in products:
                    if slodoc.app.parent_app:
                        app = f"{slodoc.app.parent_app.name}-{slodoc.app.name}"
                    else:
                        app = slodoc.app.name

                    # Check if the product or app is excluded from the desired list
                    product_or_app_excluded = (
                        product not in desired_product_apps
                        or app not in desired_product_apps.get(product, set())
                    )

                    # Check if statusBoard label exists and is explicitly disabled
                    status_board_enabled = (
                        slodoc.labels is not None
                        and "statusBoard" in slodoc.labels
                        and slodoc.labels["statusBoard"] == "enabled"
                    )

                    if product_or_app_excluded or not status_board_enabled:
                        continue

                    desired_abstract_status_board_map[f"{product}/{app}/{slo.name}"] = {
                        "type": "service",
                        "product": product,
                        "app": app,
                        "service": slo.name,
                        "metadata": {
                            "sli_type": slo.sli_type,
                            "sli_specification": slo.sli_specification,
                            "slo_details": slo.slo_details,
                            "target": slo.slo_target,
                            "target_unit": slo.slo_target_unit,
                            "window": slo.slo_parameters.window,
                        },
                    }

        return desired_abstract_status_board_map

    @staticmethod
    def current_abstract_status_board_map(
        current_products_applications_services: Iterable[Product],
    ) -> Mapping[str, dict[str, Any]]:
        return_value: dict[str, dict[str, Any]] = {}
        for product in current_products_applications_services:
            pass
            return_value[product.name] = {
                "type": "product",
                "product": product.name,
                "app": "",
            }
            for app in product.applications or []:
                return_value[f"{product.name}/{app.name}"] = {
                    "type": "app",
                    "product": product.name,
                    "app": app.name,
                }
                for service in app.services or []:
                    key = f"{product.name}/{app.name}/{service.name}"
                    return_value[key] = {
                        "type": "service",
                        "product": product.name,
                        "app": app.name,
                        "service": service.name,
                        "metadata": service.metadata,
                    }
                    # return_value[key].update(service.metadata or {})

        return return_value

    @staticmethod
    def get_diff(
        desired_abstract_status_board_map: Mapping[str, dict[str, Any]],
        current_abstract_status_board_map: Mapping[str, dict[str, Any]],
        current_products: Mapping[str, Product],
    ) -> list[StatusBoardHandler]:
        def create_app(
            app_name: str,
            product: Product,
        ) -> Application:
            return Application(
                name=app_name,
                fullname=f"{product.name}/{app_name}",
                product=product,
            )

        return_list: list[StatusBoardHandler] = []

        diff_result = diff_mappings(
            current_abstract_status_board_map,
            desired_abstract_status_board_map,
        )

        products_to_create = [
            p for _, p in diff_result.add.items() if p["type"] == "product"
        ]
        apps_to_create = [a for _, a in diff_result.add.items() if a["type"] == "app"]
        services_to_create = [
            s for _, s in diff_result.add.items() if s["type"] == "service"
        ]

        # Create apps for products that already exists
        if apps_to_create:
            for name, p in current_products.items():
                this_product_apps = [a for a in apps_to_create if a["product"] == name]
                for a in this_product_apps or []:
                    appplication = create_app(app_name=a["app"], product=p)
                    return_list.append(
                        StatusBoardHandler(
                            action=Action.create, status_board_object=appplication
                        )
                    )
                    this_app_services = [
                        s for s in services_to_create if s["app"] == appplication.name
                    ]
                    for s in this_app_services:
                        name = s["service"]
                        fullname = f"{p.name}/{appplication.name}/{name}"
                        metadata = s["metadata"]

                        return_list.append(
                            StatusBoardHandler(
                                action=Action.create,
                                status_board_object=Service(
                                    name=name,
                                    fullname=fullname,
                                    metadata=metadata,
                                    application=appplication,
                                ),
                            )
                        )

        # Create products, apps, and their services
        for p in products_to_create or []:
            product = Product(name=p["product"], fullname=p["product"])
            return_list.append(
                StatusBoardHandler(
                    action=Action.create,
                    status_board_object=product,
                )
            )
            this_product_apps = [
                a for a in apps_to_create if a["product"] == product.name
            ]
            for a in this_product_apps or []:
                appplication = create_app(app_name=a["app"], product=product)
                return_list.append(
                    StatusBoardHandler(
                        action=Action.create, status_board_object=appplication
                    )
                )
                this_app_services = [
                    s for s in services_to_create if s["app"] == appplication.name
                ]
                for s in this_app_services:
                    name = s["service"]
                    fullname = f"{product.name}/{appplication.name}/{name}"
                    metadata = s["metadata"]

                    return_list.append(
                        StatusBoardHandler(
                            action=Action.create,
                            status_board_object=Service(
                                name=name,
                                fullname=fullname,
                                metadata=metadata,
                                application=appplication,
                            ),
                        )
                    )

        # Creating services for existing apps and products
        if services_to_create:
            for p in current_products.values():
                for a in p.applications or []:
                    this_app_services = [
                        s for s in services_to_create if s["app"] == a.name
                    ]
                    for s in this_app_services or []:
                        name = s["service"]
                        fullname = f"{p.name}/{a.name}/{name}"
                        metadata = s["metadata"]

                        return_list.append(
                            StatusBoardHandler(
                                action=Action.create,
                                status_board_object=Service(
                                    name=name,
                                    fullname=fullname,
                                    metadata=metadata,
                                    application=a,
                                ),
                            )
                        )

        services_to_delete = [
            s for _, s in diff_result.delete.items() if s["type"] == "service"
        ]
        apps_to_delete = [
            a for _, a in diff_result.delete.items() if a["type"] == "app"
        ]
        products_to_delete = [
            p for _, p in diff_result.delete.items() if p["type"] == "product"
        ]

        for s in services_to_delete:
            apps = current_products[s["product"]].applications
            [app] = [a for a in apps or [] if a.name == s["app"]]
            [service] = [svr for svr in app.services or [] if svr.name == s["service"]]

            return_list.append(
                StatusBoardHandler(action=Action.delete, status_board_object=service)
            )

        for a in apps_to_delete:
            apps = current_products[a["product"]].applications
            [application] = [app for app in apps or [] if app.name == a["app"]]

            return_list.append(
                StatusBoardHandler(
                    action=Action.delete, status_board_object=application
                )
            )

        for p in products_to_delete:
            product = current_products[p["product"]]

            return_list.append(
                StatusBoardHandler(action=Action.delete, status_board_object=product)
            )

        services_to_update = [
            s.desired
            for _, s in diff_result.change.items()
            if s.current["type"] == "service"
        ]
        for s in services_to_update:
            product = current_products[s["product"]]
            [application] = [
                a for a in product.applications or [] if a.name == s["app"]
            ]
            [service_id] = [
                svr.id for svr in application.services or [] if svr.name == s["service"]
            ]
            name = s["service"]
            fullname = f"{product.name}/{application.name}/{name}"
            metadata = s["metadata"]
            service = Service(id=service_id, name=name, fullname=fullname, metadata=metadata)

            return_list.append(
                StatusBoardHandler(action=Action.update, status_board_object=service)
            )

        return return_list

    @staticmethod
    def apply_diff(
        dry_run: bool, ocm_api: OCMBaseClient, diff: list[StatusBoardHandler]
    ) -> None:
        creations: list[StatusBoardHandler] = []
        deletions: list[StatusBoardHandler] = []

        for o in diff:
            match o.action:
                case Action.create:
                    creations.append(o)
                case Action.delete:
                    deletions.append(o)

        # Products need to be created before Applications
        creations.sort(key=lambda x: x.status_board_object.get_priority())

        # Applications need to be deleted before Products
        deletions.sort(key=lambda x: x.status_board_object.get_priority(), reverse=True)

        for d in creations + deletions:
            d.act(dry_run, ocm_api)

    def run(self, dry_run: bool) -> None:
        # update cyclic reference
        Product.update_forward_refs()

        slodocs = get_slo_documents()
        for sb in get_status_board():
            ocm_api = init_ocm_base_client(sb.ocm, self.secret_reader)

            # Desired state
            desired_product_apps: dict[str, set[str]] = self.get_product_apps(sb)
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

            current_products = {
                p.name: p for p in current_products_applications_services
            }
            diff = self.get_diff(
                desired_abstract_status_board_map,
                current_abstract_status_board_map,
                current_products,
            )

            self.apply_diff(dry_run, ocm_api, diff)
