# Rotate legacy terraform-resources IAM keys without downtime

Use `qontract-cli terraform-resources rotate-access-key` for IAM users created by
legacy `terraform-resources`, including S3, S3/CloudFront, service accounts, and
CloudWatch resources. For ERv2 CloudWatch resources, use the separate
`qontract-cli external-resources ... rotate-access-key` command.

This procedure preserves the old Active key while normal reconciliation creates
a second key. Applications can continue using the old credential during cutover.
Retire the old key only after verifying that every consumer has adopted the new
credential.

## Exclusive mutation window

Mutating rotation and retirement commands acquire shared S3 locks through the
configured app-interface state store, before their first key/state inventory
read, and retain them through mutation and final verification. Inspection and
`--verify` do not create locks. All operators must use the same state store.
Execution needs read/write/delete access to its
`state/iam-key-rotation-locks/` prefix, including IAM-only retirement.

The IAM-user lock is shared by legacy preparation, deactivation, and deletion,
using the AWS account ID and username rather than the selected key
ID. Legacy preparation also locks its shared Terraform backend, so two users
cannot concurrently edit the same account state.

These locks coordinate these CLI commands. Terraform workers, other integrations,
manual Terraform sessions, and direct IAM calls do not participate. Before
mutation, pause other writers for the selected state/IAM user and wait for
in-flight operations to finish. Keep this exclusive window through command
completion. Normal reconciliation can resume after preparation returns; pause
any competing key writer again for final retirement. A per-command Terraform
backend lock alone does not protect the inspection-to-mutation interval.

Locks use conditional S3 creation and owner-conditional release. They have no
automatic expiry or takeover. If a process crashes or a response is lost, locate
the lock object reported in the error or under the prefix above, confirm that
its process and any other writers have stopped, and remove that orphaned lock
before retrying. Do not remove a lock held by a live process.

## 1. Inspect the user and record its metadata

Use the configuration and state/cache environment for the intended deployment.
The cache uses the same app-interface state configuration as
`qontract-cli early-exit-cache`.

```sh
qontract-cli --config config.debug.toml terraform-resources rotate-access-key \
  --account ACCOUNT --iam-user IAM_USER
```

Review the AWS account, backend bucket/key, Terraform version, managed key ID,
state address, cache bucket/key, and all consumer bindings in the JSON result.
Execution needs the inspected key ID, address, and cache bucket. Use a Terraform
executable whose version exactly matches the remote state.

The IAM user must have exactly one access key, and it must be Active. The old key must not be
listed in the account's `deleteKeys`; resolve any pending retirement before
proceeding. The command refuses ERv2 declarations and unsupported state instances.

## 2. Disable integrations that write the shared account state

Record the original integration controls and coordinate the rotation window with
the on-call engineer. Disable `terraform-resources` using its Unleash feature
toggle or the target AWS account's app-interface configuration:

```yaml
disable:
  integrations:
  - terraform-resources
```

Preserve existing disabled entries if using the account-level setting. Disable
the standalone `aws-iam-keys` integration using its Unleash feature toggle or by
pausing its scheduled execution. The legacy `aws-iam-keys` account filter does not
honor an account-level `disable.integrations: [aws-iam-keys]` entry; that entry
alone is insufficient. Disable any additional workflow that writes the same
backend bucket/key, and coordinate manual Terraform operations for the account.

Verify that automation has loaded the changed controls. For account configuration
changes, merge them and verify that the running integration sees the new bundle.
Unleash integration disables can also suppress the corresponding PR validation;
keep the window brief and coordinate unrelated Terraform changes.

Wait for already-running jobs and manual state operations to finish before proceeding;
disabling an integration does not terminate its in-flight runs. The legacy backend
configuration has no state lock, so no concurrent writer may edit this state
during preparation. The CLI relies on this SOP and does not disable integrations.

## 3. Prepare one or more users while writers are disabled

```sh
qontract-cli --config config.debug.toml terraform-resources rotate-access-key \
  --account ACCOUNT --iam-user IAM_USER \
  --expected-key-id OLD_KEY_ID \
  --expected-address aws_iam_access_key.RESOURCE_NAME \
  --expected-cache-bucket CACHE_BUCKET \
  --terraform-binary /path/to/matching/terraform \
  --no-dry-run
```

Use the inspected values. If the deployed integration version differs from the
CLI's default, pass `--integration-version VERSION` for its reconciliation cache.

The command previews and removes only the selected key binding from Terraform
state. It checks the complete shared state before and after removal, keeps the
old AWS key Active, and invalidates the account's reconciliation cache entry.
It also invalidates the unscoped no-dry-run cache entry, so reconciliation without
an account filter cannot reuse a pre-preparation cache hit. Dry-run caches are
unchanged. It does not run Terraform apply or retire IAM keys. A `requested` result means
preparation succeeded; the new key will be created after reconciliation resumes.

Repeat sequentially for additional users in the same account before re-enabling
writers. Save the metadata needed for each verification; keep credential values
out of progress records.

## 4. Re-enable reconciliation and verify consumers

Before re-enabling reconciliation, recheck that none of the retained old keys has
been added to `deleteKeys`. `terraform-resources` invokes IAM-key cleanup directly,
so disabling the standalone `aws-iam-keys` feature toggle does not suppress that
inline cleanup.

Restore the `terraform-resources` control changed for this rotation: re-enable its
feature toggle or remove the account disable entry and merge that change,
preserving pre-existing disables. Wait for reconciliation to create the
replacement keys and synchronize their source Secrets. Normal account
reconciliation can also apply other reviewed pending account changes.

```sh
qontract-cli --config config.debug.toml terraform-resources rotate-access-key \
  --account ACCOUNT --iam-user IAM_USER \
  --expected-key-id OLD_KEY_ID \
  --expected-address aws_iam_access_key.RESOURCE_NAME \
  --verify
```

`key_created` confirms an Active new managed key, an Active retained old key, and
matching Terraform outputs. This does not verify source Secrets or application
adoption: the JSON explicitly reports `source_secret_sync_verified: false` and
`consumer_verification_required: true`.

Check every listed source Secret against the new key ID. Coordinate any required
application refreshes with owners, then verify successful application operations
using the new credential. Keep the old key Active until every consumer's cutover
has been verified.

## 5. Retire old keys and restore remaining integrations

After verifying every consumer has adopted the replacement, preview retirement
of the original old key with one command:

```sh
qontract-cli --config config.debug.toml terraform-resources delete-access-key \
  --account ACCOUNT --iam-user IAM_USER --key-id OLD_KEY_ID
```

The command defaults to dry run. It accepts one selected key ID and requires
another Active key on the same IAM user. It checks IAM directly without reading
Terraform state, namespace declarations, or reconciliation caches. An Active key
does not prove that applications have adopted it; verify cutover first.

Add `--no-dry-run` to execute. If the old key is Active, the command deactivates
it, verifies it is Inactive, and then deletes it in the same invocation. An
already-Inactive old key is deleted directly. There is no observation pause
between deactivation and deletion; complete application-level cutover verification
before execution. The command cannot determine whether the old key is unused.

For an observation period before deletion, optionally run the separate
`deactivate-access-key` command with the same account, user, and old key arguments.
It also defaults to dry run. Add `--no-dry-run` to deactivate, observe consumers,
and then use `delete-access-key` when ready. If cutover needs correction before
deletion, reactivate the retained key through IAM.

Both retirement commands leave Terraform state and its cache unchanged. They
recheck that another Active key remains before mutations and after each phase.
They do not verify Terraform ownership: deleting a currently managed key may
cause normal reconciliation to recreate it. A retry after a lost
response can resume from an Inactive old key or report an already-deleted key
without repeating completed mutations.

The shared IAM-user lock prevents two CLI invocations from simultaneously
retiring opposite keys. Other key writers must still be stopped as described
under **Exclusive mutation window**, even when the selected key is not listed
in `deleteKeys`.

Deactivation alone does not free a key slot: Active and Inactive keys both occupy
one. Successful deletion reports `available_key_slots: 1` and the remaining
Active key ID. `rotate-access-key` never retires old keys
automatically; explicit deletion is a separate step after consumer verification.

Restore the remaining integration controls changed for this rotation, including
the standalone `aws-iam-keys` feature toggle or schedule, while preserving
pre-existing disables. Confirm normal reconciliation has resumed. A later
`--verify` can report `old_key_retired` once
the old key is absent and the replacement remains Active with matching outputs.

## Interrupted preparation

Keep state writers disabled while investigating a preparation failure. If the key
binding was already removed but the response or cache invalidation failed, rerun
with the same original key ID, address, and cache bucket. The command can resume
without removing another binding. If it reports a changed key or unexpected state,
inspect before continuing; do not substitute a newly created key as the old key.
