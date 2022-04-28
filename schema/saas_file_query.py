import sgqlc.types
import sgqlc.operation
import schema.qontract_schema

_schema = schema.qontract_schema
_schema_root = _schema.qontract_schema

__all__ = ('Operations',)


def query_list_saas_files_v2():
    _op = sgqlc.operation.Operation(_schema_root.query_type, name='ListSaasFilesV2')
    _op_apps = _op.apps_v1(__alias__='apps')
    _op_apps_saas_files_v2 = _op_apps.saas_files_v2()
    _op_apps_saas_files_v2.name()
    _op_apps_saas_files_v2_pipelines_provider = _op_apps_saas_files_v2.pipelines_provider()
    _op_apps_saas_files_v2_pipelines_provider.name()
    return _op


class Query:
    list_saas_files_v2 = query_list_saas_files_v2()


class Operations:
    query = Query
