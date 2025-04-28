from reconcile.gql_definitions.fragments.saas_slo_document import SLODocument
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.slo_document_manager import SLODetails, SLODocumentManager


class SLOGateKeeper:
    """
    Evaluate the SLO Documents using SLODOcumentManager and identifies breached SLOs
    """

    def __init__(
        self,
        slo_documents: list[SLODocument],
        secret_reader: SecretReaderBase,
        thread_pool_size: int = 1,
    ):
        self.slo_manager_list = SLODocumentManager.get_slo_document_manager_list(
            slo_documents, secret_reader, thread_pool_size
        )

    def get_breached_slos(self) -> list[SLODetails]:
        current_slos: list[SLODetails] = []
        for slo_manager in self.slo_manager_list:
            try:
                current_slos.extend(slo_manager.get_slo_details_list())
            finally:
                slo_manager.cleanup()

        exceptions = [slo for slo in current_slos if isinstance(slo, Exception)]
        if exceptions:
            raise RuntimeError(
                f"found exceptions while getting the slo details {exceptions}"
            )

        breached_slos = [
            slo for slo in current_slos if slo.current_slo_value < slo.slo.slo_target
        ]
        return breached_slos
