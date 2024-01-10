# Integration change-owners

`change-owners` uses change-type declarations from `app-interface` to grant self-service change permissions to `app-interface` tenants.


## Module structure

* `reconcile.change_owners.diff` contains all functionality for low-level diffing on file content. It can be used to extract differences from files as `Diff` dataclasses.
* `reconcile.change_owners.change_types` uses the `diff` module to extract relevant changes and tries to cover them with `change-types` from `app-interface`. The results are `BundleFileChange` dataclasses that contain all the found changes along with the `change-types` covering them. A change is considered `covered` when at least one `change-type` allows the changes in a context that provides approvers.
* `reconcile.change_owners.self_service_roles` is a change coverage implementation that uses `RoleV1.self_service` configurations from `app-interface` to bring changes, change-types and approvers together in a `ChangeTypeContext`.
* `reconcile.change_owners.decision` handles MR decision command parsing from eligible change approvers.
* `reconcile.change_owners.change_owners` is the entry point for the integrations and acts mostly as a coordinator between the other modules.

## Functionality

`change_owners` uses the `qontract-server` diff endpoint to get a highlevel overview what changed in an MR. It leverages `change_types` to find fine grained differences in datafiles and resourcefiles and build `BundleFileChange` objects that hold the state of diffs and diff coverage.

`change_owners` checks `BundleFileChange` objects for `change-types` that are `restrictive`. If the MR was created by a user, that has this `change-type` not assigned, the integration will fail. A user with this role assigned could issue an `/good-to-test` command to override this restriction.

`change_owners` reachs out to pluggable functionality to find out which `change-types` can be applied to which changes with a set of approvers. Currently, the only module to provide such `ChangeTypeContext` is `self_service_roles` which looks for explicitly bound `change-types` and files in the context of a `Role` with users and bots will can act as approvers.

The functionality provided by `self_service_roles` is very explicit because it sets up the self-service relationship by listing all involved components. Other mechanisms to provide `ChangeTypeContexts` based on other explicit or implicit ownership information can be added easily and plugged into the `change_owners.cover_changes()` function.

The result of this coverage process is a list of `BundleFileChange` objects, each of them having a list of `DiffCoverage` objects, listing all differences and how (and if) they are covered by `ChangeTypeContexts`. That way every change has a list of `Approvers` provided by the context of the `ChangeType`.

Next, `change_owners` reaches out to the `app-interface MR` it processes, to find the decisions of the approvers. Decisions are given as `/` command comments on the MR. The `decision` module parses those comments and applies them to the `BundleFileChanges` and their `DiffCoverage` objects. The result is a list of `ChangeDecisions` where every change is `approved` and/or on `hold`.

The `change_owners` module inspects those `ChangeDecisions` to find out if all changes have been approved. If that is the case, it adds the `bot/approved` label to the MR so that `gitlab-housekeeper` can act on the MR and will try to merge it.

If at least one `ChangeDecision` is on `hold`, the `bot/hold` label is applied, which prevents `gitlab-housekeeper` from merging.

If at least one `ChangeDecision` is not `approved`, the the MR can not proceed without further approvals or without AppSRE intervention.

In the case of changes not having a `ChangeTypeContext` attached allowing approvers to decide, the MR is considered `non-self-serviceable` and can't proceed without AppSRE intervention.
