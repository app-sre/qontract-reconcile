"""Tests for GitLab Repository API client with hooks."""

# ruff: file-ignore[unused-function-argument]
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.hooks import Hooks
from qontract_utils.vcs.provider_protocol import (
    AUTO_MERGE_LABEL,
    CreateMergeRequestInput,
    FileAction,
    MergeRequestFile,
    MergeRequestInfo,
)
from qontract_utils.vcs.providers.gitlab_client import (
    GitLabApiCallContext,
    GitLabRepoApi,
)


@pytest.fixture
def mock_gitlab_client() -> Generator[MagicMock]:
    """Mock GitLab client."""
    with patch(
        "qontract_utils.vcs.providers.gitlab_client.gitlab.Gitlab"
    ) as mock_client:
        yield mock_client


@pytest.fixture
def gitlab_api(mock_gitlab_client: MagicMock) -> GitLabRepoApi:
    """Create GitLabRepoApi instance with mocked client."""
    return GitLabRepoApi(
        project_id="test-group/test-project",
        token="test-token",
        gitlab_url="https://gitlab.com",
    )


def test_gitlab_api_pre_hooks_includes_metrics_and_latency(
    mock_gitlab_client: MagicMock,
) -> None:
    """Test that metrics and latency hooks are always included."""
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
    )

    # Should have metrics, latency_start, and request_log hooks
    assert len(api._hooks.pre_hooks) >= 3


def test_gitlab_api_pre_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom pre_hooks are added after built-in hooks."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        hooks=Hooks(pre_hooks=[custom_hook]),
    )

    # Should have built-in hooks + custom hook
    assert len(api._hooks.pre_hooks) == 4
    assert custom_hook in api._hooks.pre_hooks


def test_gitlab_api_post_hooks_includes_latency(
    mock_gitlab_client: MagicMock,
) -> None:
    """Test that latency_end hook is always included in post_hooks."""
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
    )

    # Should have at least the latency_end hook
    assert len(api._hooks.post_hooks) >= 1


def test_gitlab_api_post_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom post_hooks are added after latency hook."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        hooks=Hooks(post_hooks=[custom_hook]),
    )

    # Should have latency_end hook + custom hook
    assert len(api._hooks.post_hooks) == 2
    assert custom_hook in api._hooks.post_hooks


def test_gitlab_api_error_hooks_custom(mock_gitlab_client: MagicMock) -> None:
    """Test custom error_hooks are added."""
    custom_hook = MagicMock()
    api = GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        hooks=Hooks(error_hooks=[custom_hook]),
    )

    # Should have custom error hook
    assert len(api._hooks.error_hooks) == 1
    assert api._hooks.error_hooks[0] == custom_hook


def test_gitlab_api_get_file_calls_pre_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file calls pre_hooks before API call."""
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])

    # Mock project files.get
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(gitlab_api._project.files, "get", return_value=mock_file):
        gitlab_api.get_file("test.txt")

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://gitlab.com/test-group/test-project"


def test_gitlab_api_get_file_calls_post_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file calls post_hooks after API call."""
    post_hook = MagicMock()
    gitlab_api._hooks = Hooks(post_hooks=[post_hook])

    # Mock project files.get
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(gitlab_api._project.files, "get", return_value=mock_file):
        gitlab_api.get_file("test.txt")

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert context.method == "get_file"
    assert context.repo_url == "https://gitlab.com/test-group/test-project"


def test_gitlab_api_get_file_returns_content(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file returns file content."""
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(
        gitlab_api._project.files, "get", return_value=mock_file
    ) as mock_get:
        result = gitlab_api.get_file("test.txt")

    assert result == "file content"
    mock_get.assert_called_once_with(file_path="test.txt", ref="master")


def test_gitlab_api_get_file_with_custom_ref(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file with custom ref parameter."""
    mock_file = MagicMock()
    mock_file.decode.return_value.decode.return_value = "file content"
    with patch.object(
        gitlab_api._project.files, "get", return_value=mock_file
    ) as mock_get:
        result = gitlab_api.get_file("test.txt", ref="develop")

    assert result == "file content"
    mock_get.assert_called_once_with(file_path="test.txt", ref="develop")


def test_gitlab_api_get_file_returns_none_on_exception(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test get_file returns None when file not found."""
    with patch.object(
        gitlab_api._project.files, "get", side_effect=Exception("Not found")
    ):
        result = gitlab_api.get_file("nonexistent.txt")

    assert result is None


def test_gitlab_api_find_merge_request_found(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test find_merge_request returns URL when MR with matching title exists."""
    mock_mr = MagicMock()
    mock_mr.title = "[ldap-users] delete user alice"
    mock_mr.web_url = "https://gitlab.com/group/project/-/merge_requests/42"
    with patch.object(
        gitlab_api._project.mergerequests,
        "list",
        return_value=[mock_mr],
    ) as mock_list:
        result = gitlab_api.find_merge_request("[ldap-users] delete user alice")

    assert result == "https://gitlab.com/group/project/-/merge_requests/42"
    mock_list.assert_called_once_with(
        search="[ldap-users] delete user alice",
        state="opened",
        per_page=100,
        iterator=True,
    )


def test_gitlab_api_find_merge_request_not_found(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test find_merge_request returns None when no MR matches."""
    with patch.object(
        gitlab_api._project.mergerequests,
        "list",
        return_value=[],
    ):
        result = gitlab_api.find_merge_request("nonexistent title")

    assert result is None


def test_gitlab_api_find_merge_request_no_exact_match(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test find_merge_request returns None when search returns partial matches only."""
    mock_mr = MagicMock()
    mock_mr.title = "[ldap-users] delete user alice AND bob"
    with patch.object(
        gitlab_api._project.mergerequests,
        "list",
        return_value=[mock_mr],
    ):
        result = gitlab_api.find_merge_request("[ldap-users] delete user alice")

    assert result is None


def test_gitlab_api_find_merge_request_calls_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test find_merge_request triggers hooks."""
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])

    with patch.object(gitlab_api._project.mergerequests, "list", return_value=[]):
        gitlab_api.find_merge_request("some title")

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "find_merge_request"


def _mock_mr(
    title: str,
    web_url: str,
    *,
    description: str = "",
    labels: list[str] | None = None,
    has_conflicts: bool = False,
) -> MagicMock:
    """Create a mock python-gitlab merge request object."""
    mr = MagicMock()
    mr.title = title
    mr.description = description
    mr.web_url = web_url
    mr.labels = labels or []
    mr.has_conflicts = has_conflicts
    return mr


def test_gitlab_api_list_open_merge_requests(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test list_open_merge_requests maps GitLab objects to MergeRequestInfo."""
    mock_mr = _mock_mr(
        "[auto] endpoints-discovery: update application endpoints",
        "https://gitlab.com/group/project/-/merge_requests/42",
        description="description body",
        labels=["ENDPOINTS-DISCOVERY"],
        has_conflicts=True,
    )
    with patch.object(
        gitlab_api._project.mergerequests, "list", return_value=[mock_mr]
    ) as mock_list:
        result = gitlab_api.list_open_merge_requests()

    assert result == [
        MergeRequestInfo(
            title="[auto] endpoints-discovery: update application endpoints",
            description="description body",
            web_url="https://gitlab.com/group/project/-/merge_requests/42",
            labels=["ENDPOINTS-DISCOVERY"],
            has_conflicts=True,
        )
    ]
    mock_list.assert_called_once_with(state="opened", per_page=100, iterator=True)


def test_gitlab_api_list_open_merge_requests_with_label(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test list_open_merge_requests passes a label filter to GitLab."""
    with patch.object(
        gitlab_api._project.mergerequests, "list", return_value=[]
    ) as mock_list:
        result = gitlab_api.list_open_merge_requests(label="ENDPOINTS-DISCOVERY")

    assert result == []
    mock_list.assert_called_once_with(
        state="opened",
        per_page=100,
        iterator=True,
        labels="ENDPOINTS-DISCOVERY",
    )


def test_gitlab_api_list_open_merge_requests_with_title_filters_exact(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test a title filter keeps only exact matches, like find_merge_request."""
    exact = _mock_mr(
        "update application endpoints",
        "https://gitlab.com/group/project/-/merge_requests/1",
    )
    partial = _mock_mr(
        "update application endpoints and more",
        "https://gitlab.com/group/project/-/merge_requests/2",
    )
    with patch.object(
        gitlab_api._project.mergerequests, "list", return_value=[exact, partial]
    ) as mock_list:
        result = gitlab_api.list_open_merge_requests(
            title="update application endpoints"
        )

    assert [mr.web_url for mr in result] == [
        "https://gitlab.com/group/project/-/merge_requests/1"
    ]
    mock_list.assert_called_once_with(
        state="opened",
        per_page=100,
        iterator=True,
        search="update application endpoints",
    )


def test_gitlab_api_list_open_merge_requests_calls_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test list_open_merge_requests triggers hooks."""
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])

    with patch.object(gitlab_api._project.mergerequests, "list", return_value=[]):
        gitlab_api.list_open_merge_requests()

    pre_hook.assert_called_once()
    assert pre_hook.call_args[0][0].method == "list_open_merge_requests"


def test_gitlab_api_close_merge_request_with_comment(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test close_merge_request comments then closes the MR."""
    mock_mr = _mock_mr("title", "https://gitlab.com/group/project/-/merge_requests/42")
    with patch.object(
        gitlab_api._project.mergerequests, "get", return_value=mock_mr
    ) as mock_get:
        gitlab_api.close_merge_request(
            "https://gitlab.com/group/project/-/merge_requests/42",
            comment="Closing this MR because it's outdated.",
        )

    mock_get.assert_called_once_with(42)
    mock_mr.notes.create.assert_called_once_with(
        {"body": "Closing this MR because it's outdated."}
    )
    assert mock_mr.state_event == "close"
    mock_mr.save.assert_called_once_with()


def test_gitlab_api_close_merge_request_without_comment(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test close_merge_request skips the comment when none is given."""
    mock_mr = _mock_mr("title", "https://gitlab.com/group/project/-/merge_requests/7")
    with patch.object(gitlab_api._project.mergerequests, "get", return_value=mock_mr):
        gitlab_api.close_merge_request(
            "https://gitlab.com/group/project/-/merge_requests/7"
        )

    mock_mr.notes.create.assert_not_called()
    assert mock_mr.state_event == "close"
    mock_mr.save.assert_called_once_with()


def test_gitlab_api_close_merge_request_trailing_slash(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test a trailing slash still yields the merge request IID."""
    mock_mr = _mock_mr("title", "https://gitlab.com/group/project/-/merge_requests/9/")
    with patch.object(
        gitlab_api._project.mergerequests, "get", return_value=mock_mr
    ) as mock_get:
        gitlab_api.close_merge_request(
            "https://gitlab.com/group/project/-/merge_requests/9/"
        )

    mock_get.assert_called_once_with(9)


def test_gitlab_api_close_merge_request_invalid_url(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test a URL without a numeric IID raises ValueError."""
    with pytest.raises(ValueError, match="merge request IID"):
        gitlab_api.close_merge_request("https://gitlab.com/group/project")


def test_gitlab_api_close_merge_request_calls_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test close_merge_request triggers hooks."""
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])
    mock_mr = _mock_mr("title", "https://gitlab.com/group/project/-/merge_requests/3")

    with patch.object(gitlab_api._project.mergerequests, "get", return_value=mock_mr):
        gitlab_api.close_merge_request(
            "https://gitlab.com/group/project/-/merge_requests/3"
        )

    pre_hook.assert_called_once()
    assert pre_hook.call_args[0][0].method == "close_merge_request"


def test_gitlab_api_create_merge_request(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request creates branch, applies ops, and opens MR."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/group/project/-/merge_requests/99"

    mr_input = CreateMergeRequestInput(
        title="Delete user foo",
        description="Cleanup",
        target_branch="master",
        file_operations=[
            MergeRequestFile(
                path="data/users/foo.yml",
                action=FileAction.DELETE,
                commit_message="delete user foo",
            ),
            MergeRequestFile(
                path="data/config.yml",
                action=FileAction.UPDATE,
                content="updated: true",
                commit_message="update config",
            ),
        ],
        labels=["cleanup"],
    )

    mock_file = MagicMock()
    with (
        patch.object(gitlab_api._project.branches, "create") as mock_branch_create,
        patch.object(gitlab_api._project.files, "get", return_value=mock_file),
        patch.object(gitlab_api._project.files, "create"),
        patch.object(
            gitlab_api._project.mergerequests, "create", return_value=mock_mr
        ) as mock_mr_create,
    ):
        result = gitlab_api.create_merge_request(mr_input)

    assert result == "https://gitlab.com/group/project/-/merge_requests/99"

    # Branch created with auto-generated name
    branch_call = mock_branch_create.call_args[0][0]
    assert branch_call["branch"].startswith("qontract-api-")
    assert branch_call["ref"] == "master"

    # MR created with correct title
    mr_call = mock_mr_create.call_args[0][0]
    assert mr_call["title"] == "Delete user foo"
    assert mr_call["source_branch"].startswith("qontract-api-")


def test_gitlab_api_create_merge_request_create_action(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request with CREATE action calls files.create()."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"

    mr_input = CreateMergeRequestInput(
        title="Add file",
        description="",
        file_operations=[
            MergeRequestFile(
                path="new_file.yml",
                action=FileAction.CREATE,
                content="key: value",
                commit_message="add new file",
            ),
        ],
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(gitlab_api._project.files, "create") as mock_file_create,
        patch.object(gitlab_api._project.mergerequests, "create", return_value=mock_mr),
    ):
        gitlab_api.create_merge_request(mr_input)

    mock_file_create.assert_called_once()
    call_data = mock_file_create.call_args[0][0]
    assert call_data["file_path"] == "new_file.yml"
    assert call_data["content"] == "key: value"


def test_gitlab_api_create_merge_request_update_action(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request with UPDATE action calls file.save()."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"
    mock_file = MagicMock()

    mr_input = CreateMergeRequestInput(
        title="Update file",
        description="",
        file_operations=[
            MergeRequestFile(
                path="existing.yml",
                action=FileAction.UPDATE,
                content="updated: true",
                commit_message="update file",
            ),
        ],
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(gitlab_api._project.files, "get", return_value=mock_file),
        patch.object(gitlab_api._project.mergerequests, "create", return_value=mock_mr),
    ):
        gitlab_api.create_merge_request(mr_input)

    assert mock_file.content == "updated: true"
    mock_file.save.assert_called_once()


def test_gitlab_api_create_merge_request_delete_action(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request with DELETE action calls file.delete()."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"
    mock_file = MagicMock()

    mr_input = CreateMergeRequestInput(
        title="Delete file",
        description="",
        file_operations=[
            MergeRequestFile(
                path="old_file.yml",
                action=FileAction.DELETE,
                commit_message="delete file",
            ),
        ],
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(gitlab_api._project.files, "get", return_value=mock_file),
        patch.object(gitlab_api._project.mergerequests, "create", return_value=mock_mr),
    ):
        gitlab_api.create_merge_request(mr_input)

    mock_file.delete.assert_called_once()


def test_gitlab_api_create_merge_request_auto_merge(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request adds auto-merge label when requested."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"

    mr_input = CreateMergeRequestInput(
        title="Auto MR",
        description="",
        file_operations=[],
        labels=["existing-label"],
        auto_merge=True,
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(
            gitlab_api._project.mergerequests, "create", return_value=mock_mr
        ) as mock_mr_create,
    ):
        gitlab_api.create_merge_request(mr_input)

    created_labels = mock_mr_create.call_args[0][0]["labels"]
    assert AUTO_MERGE_LABEL in created_labels
    assert "existing-label" in created_labels


def test_gitlab_api_create_merge_request_no_auto_merge(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request does not add auto-merge label by default."""
    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"

    mr_input = CreateMergeRequestInput(
        title="Normal MR",
        description="",
        file_operations=[],
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(
            gitlab_api._project.mergerequests, "create", return_value=mock_mr
        ) as mock_mr_create,
    ):
        gitlab_api.create_merge_request(mr_input)

    created_labels = mock_mr_create.call_args[0][0]["labels"]
    assert AUTO_MERGE_LABEL not in created_labels


def test_gitlab_api_create_merge_request_calls_hooks(
    gitlab_api: GitLabRepoApi,
    mock_gitlab_client: MagicMock,
) -> None:
    """Test create_merge_request triggers hooks."""
    pre_hook = MagicMock()
    gitlab_api._hooks = Hooks(pre_hooks=[pre_hook])

    mock_mr = MagicMock()
    mock_mr.web_url = "https://gitlab.com/mr/1"
    mr_input = CreateMergeRequestInput(
        title="test",
        description="",
        file_operations=[],
    )

    with (
        patch.object(gitlab_api._project.branches, "create"),
        patch.object(gitlab_api._project.mergerequests, "create", return_value=mock_mr),
    ):
        gitlab_api.create_merge_request(mr_input)

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert context.method == "create_merge_request"


def test_gitlab_api_default_user_agent(mock_gitlab_client: MagicMock) -> None:
    """Test GitLabRepoApi passes the default qontract-utils User-Agent to python-gitlab."""
    GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
    )

    assert mock_gitlab_client.call_args.kwargs["user_agent"].startswith(
        "qontract-utils/"
    )


def test_gitlab_api_custom_user_agent(mock_gitlab_client: MagicMock) -> None:
    """Test GitLabRepoApi passes a custom User-Agent to python-gitlab."""
    GitLabRepoApi(
        project_id="group/project",
        token="token",
        gitlab_url="https://gitlab.com",
        user_agent="qontract-api/1.2.3",
    )

    assert mock_gitlab_client.call_args.kwargs["user_agent"] == "qontract-api/1.2.3"


def test_gitlab_api_call_context_immutable() -> None:
    """Test GitLabApiCallContext is immutable (frozen dataclass)."""
    context = GitLabApiCallContext(
        method="get_file",
        repo_url="https://gitlab.com/group/project",
    )

    with pytest.raises(AttributeError):
        context.method = "different"  # type: ignore[misc]
