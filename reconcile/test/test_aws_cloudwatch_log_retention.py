# from reconcile.aws_cloudwatch_log_retention.integration import (
#     get_app_interface_cloudwatch_retention_period,
# )


# def test_get_app_interface_cloudwatch_retention_period():
#     test_cloudwatch_list = [
#         {
#             "accountOwners": [{"email": "email@email.com", "name": "Example Team"}],
#             "cleanup": None,
#             "consoleUrl": "https://example.com/console",
#             "name": "example-account",
#             "path": "/aws/cna-testing/account.yml",
#             "uid": "1111111111",
#         },
#         {
#             "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
#             "cleanup": [
#                 {
#                     "provider": "cloudwatch",
#                     "regex": "some/path*",
#                     "retention_in_days": "90",
#                 },
#                 {
#                     "provider": "cloudwatch",
#                     "regex": "some/other/path*",
#                     "retention_in_days": "90",
#                 },
#             ],
#             "consoleUrl": "https://some-url.com/console",
#             "name": "some-account-name",
#             "uid": "0123456789",
#         },
#     ]
#     refined_cloudwatch_list = get_app_interface_cloudwatch_retention_period(
#         test_cloudwatch_list
#     )
#     assert len(refined_cloudwatch_list) == 2
