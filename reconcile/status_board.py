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
    get_selected_app_data,
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
    update_application,
    update_product,
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
    def update(self, ocm: OCMBaseClient) -> None:
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

    def update(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to update Product "{self.name}" without id')
            return
        spec = self.dict(by_alias=True)
        spec.pop("applications")
        spec.pop("id")
        update_product(ocm, self.id, spec)

    def summarize(self) -> str:
        return f'Product: "{self.name}"'

    @staticmethod
    def get_priority() -> int:
        return 0


class Application(AbstractStatusBoard):
    product: Optional["Product"]
    old_metadata: Optional[dict[str, Any]] = None  # For tracking changes during updates

    def create(self, ocm: OCMBaseClient) -> None:
        spec = self.dict(by_alias=True)
        spec.pop("id")
        spec.pop("old_metadata", None)  # Don't send old_metadata to API
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

    def update(self, ocm: OCMBaseClient) -> None:
        if not self.id:
            logging.error(f'Trying to update Application "{self.name}" without id')
            return
        spec = self.dict(by_alias=True)
        spec.pop("id")
        spec.pop("old_metadata", None)  # Don't send old_metadata to API
        product = spec.pop("product")
        product_id = product.get("id") if product else None
        if product_id:
            spec["product"] = {"id": product_id}
        update_application(ocm, self.id, spec)

    def get_metadata_diff(self) -> str:
        """Generate git-style diff for metadata changes"""
        if not self.old_metadata:
            return ""
        
        old_meta = self.old_metadata or {}
        new_meta = self.metadata or {}
        
        # Get all unique keys from both metadata dicts
        all_keys = set(old_meta.keys()) | set(new_meta.keys())
        diff_lines = []
        
        for key in sorted(all_keys):
            old_value = old_meta.get(key)
            new_value = new_meta.get(key)
            
            if old_value != new_value:
                if old_value is not None and new_value is None:
                    # Key was removed
                    diff_lines.append(f"    -{key}: {old_value}")
                elif old_value is None and new_value is not None:
                    # Key was added
                    diff_lines.append(f"    +{key}: {new_value}")
                else:
                    # Key was changed
                    diff_lines.append(f"    -{key}: {old_value}")
                    diff_lines.append(f"    +{key}: {new_value}")
        
        return "\n".join(diff_lines) if diff_lines else ""

    def summarize(self) -> str:
        base_summary = f'Application: "{self.name}" "{self.fullname}"'
        diff = self.get_metadata_diff()
        if diff:
            return f'{base_summary}\n{diff}'
        return base_summary

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
            case "update":
                self.status_board_object.update(ocm)


class StatusBoardExporterIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_product_apps(sb: StatusBoardV1) -> dict[str, dict[str, dict[str, Any]]]:
        """
        Get product apps with their metadata including saasFiles.
        Returns a mapping of product_name -> {app_name -> app_data_with_metadata}
        """
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
        desired_product_apps: Mapping[str, dict[str, dict[str, Any]]],
        current_products_applications: Iterable[Product],
    ) -> list[StatusBoardHandler]:
        def create_app(
            app_name: str, app_data: dict[str, Any], product: Product
        ) -> Application:
            return Application(
                id=None,
                name=app_name,
                fullname=f"{product.name}/{app_name}",
                metadata=app_data.get("metadata", {}),
                product=product,
            )

        def update_app(current_app: Application, app_data: dict[str, Any]) -> Application:
            # Generate fresh metadata with deploymentSaasFiles and managedBy
            new_metadata = app_data.get("metadata", {}).copy()
            new_metadata["managedBy"] = "qontract-reconcile"
            
            return Application(
                id=current_app.id,
                name=current_app.name,
                fullname=current_app.fullname,
                metadata=new_metadata,
                old_metadata=current_app.metadata,  # Store old metadata for diff
                product=current_app.product,
            )

        def metadata_differs(
            current_metadata: dict[str, Any] | None, desired_metadata: dict[str, Any]
        ) -> bool:
            # Compare metadata, focusing on deploymentSaasFiles
            current_saas_files = set(
                current_metadata.get("deploymentSaasFiles", [])
                if current_metadata
                else []
            )
            desired_saas_files = set(desired_metadata.get("deploymentSaasFiles", []))
            return current_saas_files != desired_saas_files

        def add_metadata_updates(
            product: Product,
            apps_data: dict[str, dict[str, Any]],
            return_list: list[StatusBoardHandler],
        ) -> None:
            """Helper function to add metadata update actions for a product's applications"""
            for application in product.applications or []:
                if application.name in apps_data:
                    app_data = apps_data[application.name]
                    desired_metadata = app_data.get("metadata", {})
                    if metadata_differs(application.metadata, desired_metadata):
                        return_list.append(
                            StatusBoardHandler(
                                action="update",
                                status_board_object=update_app(application, app_data),
                            )
                        )

        return_list: list[StatusBoardHandler] = []
        current_products = {p.name: p for p in current_products_applications}

        current_as_mapping: Mapping[str, set[str]] = {
            c.name: {a.name for a in c.applications or []}
            for c in current_products_applications
        }

        # Convert desired apps to the format expected by diff_mappings
        desired_as_mapping: Mapping[str, set[str]] = {
            product_name: set(apps_data.keys())
            for product_name, apps_data in desired_product_apps.items()
        }

        diff_result = diff_mappings(
            current_as_mapping,
            desired_as_mapping,
        )

        for product_name in diff_result.add:
            product = Product(
                id=None,
                name=product_name,
                fullname=product_name,
                metadata=None,
                applications=[],
            )
            return_list.append(
                StatusBoardHandler(
                    action="create",
                    status_board_object=product,
                )
            )
            # new product, so it misses also the applications
            apps_data = desired_product_apps[product_name]
            return_list.extend(
                StatusBoardHandler(
                    action="create",
                    status_board_object=create_app(app_name, app_data, product),
                )
                for app_name, app_data in apps_data.items()
            )

        # existing product, only add/remove/update applications
        for product_name, apps in diff_result.change.items():
            product = current_products[product_name]
            apps_data = desired_product_apps[product_name]

            # Create new applications
            return_list.extend(
                StatusBoardHandler(
                    action="create",
                    status_board_object=create_app(
                        app_name, apps_data[app_name], product
                    ),
                )
                for app_name in apps.desired - apps.current
            )

            # Delete removed applications
            to_delete = apps.current - apps.desired
            return_list.extend(
                StatusBoardHandler(
                    action="delete",
                    status_board_object=application,
                )
                for application in product.applications or []
                if application.name in to_delete
            )

            # Update existing applications that have metadata changes
            add_metadata_updates(product, apps_data, return_list)

        # Handle products where app names stay the same but metadata might have changed
        for product_name in diff_result.identical:
            if (
                product_name in current_products
                and product_name in desired_product_apps
            ):
                product = current_products[product_name]
                apps_data = desired_product_apps[product_name]

                # Check if any existing applications need metadata updates
                add_metadata_updates(product, apps_data, return_list)

        # product is deleted entirely
        for product_name in diff_result.delete:
            return_list.extend(
                StatusBoardHandler(action="delete", status_board_object=application)
                for application in current_products[product_name].applications or []
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
        updates: list[StatusBoardHandler] = []
        deletions: list[StatusBoardHandler] = []

        for o in diff:
            match o.action:
                case "create":
                    creations.append(o)
                case "update":
                    updates.append(o)
                case "delete":
                    deletions.append(o)

        # Products need to be created before Applications
        creations.sort(key=lambda x: x.status_board_object.get_priority())

        # Applications need to be deleted before Products
        deletions.sort(key=lambda x: x.status_board_object.get_priority(), reverse=True)

        # Updates can happen in any order but let's do products first for consistency
        updates.sort(key=lambda x: x.status_board_object.get_priority())

        for d in creations + updates + deletions:
            d.act(dry_run, ocm_api)

    def run(self, dry_run: bool) -> None:
        # update cyclic reference
        Product.update_forward_refs()

        for sb in get_status_board():
            ocm_api = init_ocm_base_client(sb.ocm, self.secret_reader)
            desired_product_apps: dict[str, dict[str, dict[str, Any]]] = (
                self.get_product_apps(sb)
            )

            current_products_applications = self.get_current_products_applications(
                ocm_api
            )

            diff = self.get_diff(desired_product_apps, current_products_applications)

            self.apply_diff(dry_run, ocm_api, diff)
