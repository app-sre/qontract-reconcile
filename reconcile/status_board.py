import logging
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable, Mapping
from typing import (
    Any,
    Optional,
)

from pydantic import BaseModel

from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
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
    get_managed_products,
    get_product_applications,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import QontractReconcileIntegration

QONTRACT_INTEGRATION = "status-board-exporter"


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


class StatusBoardHandler(BaseModel):
    action: str
    status_board_object: AbstractStatusBoard

    def act(self, dry_run: bool, ocm: OCMBaseClient) -> None:
        logging.info(f"{self.action} - {self.status_board_object.summarize()}")
        if dry_run:
            return

        match self.action:
            case "delete":
                self.status_board_object.delete(ocm)
            case "create":
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
    def get_current_products_applications(ocm_api: OCMBaseClient) -> list[Product]:
        products_raw = get_managed_products(ocm_api)
        products = [Product(**p) for p in products_raw]

        for p in products:
            if not p.id:
                logging.error(f'Product "{p.name}" has no id')
                continue
            p.applications = [
                Application(**a) for a in get_product_applications(ocm_api, p.id)
            ]

        return products

    @staticmethod
    def get_diff(
        desired_product_apps: Mapping[str, set[str]],
        current_products_applications: Iterable[Product],
    ) -> list[StatusBoardHandler]:
        def create_app(app_name: str, product: Product) -> Application:
            return Application(
                name=app_name,
                fullname=f"{product.name}/{app_name}",
                product=product,
            )

        return_list: list[StatusBoardHandler] = []
        current_products = {p.name: p for p in current_products_applications}

        current_as_mapping: Mapping[str, set[str]] = {
            c.name: {a.name for a in c.applications or []}
            for c in current_products_applications
        }

        diff_result = diff_mappings(
            current_as_mapping,
            desired_product_apps,
        )

        for product_name in diff_result.add:
            product = Product(name=product_name, fullname=product_name, applications=[])
            return_list.append(
                StatusBoardHandler(
                    action="create",
                    status_board_object=product,
                )
            )
            # new product, so it misses also the applications
            for app_name in desired_product_apps[product_name]:
                return_list.append(
                    StatusBoardHandler(
                        action="create",
                        status_board_object=create_app(app_name, product),
                    )
                )

        # existing product, only add/remove applications
        for product_name, apps in diff_result.change.items():
            product = current_products[product_name]
            for app_name in apps.desired - apps.current:
                return_list.append(
                    StatusBoardHandler(
                        action="create",
                        status_board_object=create_app(app_name, product),
                    )
                )
            to_delete = apps.current - apps.desired
            for application in product.applications or []:
                if application.name in to_delete:
                    return_list.append(
                        StatusBoardHandler(
                            action="delete",
                            status_board_object=application,
                        )
                    )

        # product is deleted entirely
        for product_name in diff_result.delete:
            for application in current_products[product_name].applications or []:
                return_list.append(
                    StatusBoardHandler(action="delete", status_board_object=application)
                )
            return_list.append(
                StatusBoardHandler(
                    action="delete", status_board_object=current_products[product_name]
                )
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
                case "create":
                    creations.append(o)
                case "delete":
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

        for sb in get_status_board():
            ocm_api = init_ocm_base_client(sb.ocm, self.secret_reader)
            desired_product_apps: dict[str, set[str]] = self.get_product_apps(sb)

            current_products_applications = self.get_current_products_applications(
                ocm_api
            )

            diff = self.get_diff(desired_product_apps, current_products_applications)

            self.apply_diff(dry_run, ocm_api, diff)
