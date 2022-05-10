from typing import Any

from code_gen.gen.schema import *


def data_to_obj(data: dict[Any, Any]) -> list[AppV1]:
    result: list[AppV1] = _list_apps_v1(data=data["apps_v1"])
    return result


def _list_apps_v1(data: list[dict[Any, Any]]) -> list[AppV1]:
    result: list[AppV1] = []
    for el in data:
        result.append(_apps_v1(el))
    return result


def _apps_v1(data: dict[Any, Any]) -> AppV1:
    result: AppV1 = AppV1()
    result.saas_files_v2 = _ListSaasFilesV2Data_list_saas_files_v2(data=data["saasFilesV2"])
    return result


def _ListSaasFilesV2Data_list_saas_files_v2(data: list[dict[Any, Any]]) -> list[SaasFileV2]:
    result: list[SaasFileV2] = []
    for el in data:
        result.append(_ListSaasFilesV2Data_saas_files_v2(el))
    return result


def _ListSaasFilesV2Data_saas_files_v2(data: dict[Any, Any]) -> SaasFileV2:
    result: SaasFileV2 = SaasFileV2()
    result.name = _ListSaasFilesV2Data_AppV1_name(data=data["name"])
    result.pipelines_provider = _ListSaasFilesV2Data_AppV1_pipelines_provider(data=data["pipelinesProvider"])
    return result


def _ListSaasFilesV2Data_AppV1_name(data: str) -> str:
    return str(data)


def _ListSaasFilesV2Data_AppV1_pipelines_provider(data: dict[Any, Any]) -> PipelinesProviderV1:
    result: PipelinesProviderV1 = PipelinesProviderV1()
    result.name = _ListSaasFilesV2Data_AppV1_SaasFileV2_name(data=data["name"])
    return result


def _ListSaasFilesV2Data_AppV1_SaasFileV2_name(data: str) -> str:
    return str(data)
