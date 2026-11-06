# app-interface JSONPath query inventory

Date: 2026-11-05

Ticket: <https://redhat.atlassian.net/browse/APPSRE-15715>

Migration plan: see [jsonpath-migration-proposal.md](jsonpath-migration-proposal.md) (the detailed milestone plan is still in progress, not yet published).

## Snapshot and scope

- Checkout: `/Users/cassing/workspace/gitlab-cee/cassing/app-interface`.
- HEAD: `525a2b1ee2717889e0e23336fe80276ac58ea7b0`; current working-tree contents were read, including untracked candidate configuration files.
- Scanned 18496 tracked/candidate text files; skills, agent rules, environment files, and credential-bearing local configuration are excluded.
- 1020 query occurrences, 385 distinct source expressions, 243 files.
- Includes structured selectors, ownership selectors, patch paths/JSONPath identifiers, embedded generator YAML, fixtures, and parseable YAML examples in documentation.
- Dynamic Jinja calls and other textual references are listed separately, not miscounted as static expressions.
- Kubernetes CLI JSONPath is a different implementation and must not be rewritten for this migration.
- This is a local snapshot, not a live rendered-bundle census. Dynamic template inputs and generated backrefs need runtime validation.

## Method and status legend

YAML node traversal preserves file lines and indexed field paths. Candidate configuration is found by field names rather than by requiring JSONPath expressions to contain `$`. Embedded generator strings are parsed as YAML when possible. A second raw-text sweep captures Jinja calls, CLI dialects, validation code, and documentation references.

Queries were compile-tested with `jsonpath-ng==1.8.0` and `python-jsonpath==2.2.2` on CPython 3.14. `accepted` means parsing only, not output or permission parity. Templated expressions were tested with their literal placeholders intact; render and retest before implementation.

Candidate rewrites are generated offline from the legacy AST for the supported simple selectors/comparisons and then compile-tested. They are review suggestions, not a production translator or automatic changes. Regex rewrites use `search`, not full-match semantics. Array/scalar behavior, coercion, ordering, duplicate matches, and context substitution still require fixture-based differential tests.

## Summary by category

| Category                  | Occurrences | Files | Distinct expressions | Target parse failures |
| ------------------------- | ----------: | ----: | -------------------: | --------------------: |
| change-type selector      |         462 |   134 |                  291 |                    13 |
| implicit ownership        |           6 |     6 |                    5 |                     4 |
| namespace selector        |         386 |    42 |                   24 |                    24 |
| ownership context         |          86 |    29 |                   33 |                    21 |
| status-board selector     |           2 |     2 |                    1 |                     0 |
| template patch identifier |          12 |    12 |                    4 |                     0 |
| template patch path       |          66 |    66 |                   33 |                    18 |

### Source kinds

| Source                               | Occurrences |
| ------------------------------------ | ----------: |
| configuration                        |         987 |
| documentation example                |          18 |
| expected generated output            |          10 |
| template generator (text extraction) |           5 |

## Unique query catalog

Every exact source expression has a stable ID within this snapshot. Every occurrence is indexed in the file-by-file section.

### Q001

```text
$
```

- Uses: 50 occurrences in 46 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q002

```text
$.access
```

- Uses: 11 occurrences in 11 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q003

```text
$.allowedSecretParameterPaths
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q004

```text
$.aws_groups
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q005

```text
$.cluster["$ref"]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q006

```text
$.externalResources
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q007

```text
$.externalResources[?provisioner.'$ref'=='/aws/{{ static.name }}/account.yml'].resources
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'provisioner'.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["externalResources"][?(@["provisioner"]["$ref"] == "/aws/{{ static.name }}/account.yml")]["resources"]
```

- Candidate parser: accepted.

### Q008

```text
$.managedUsergroups
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q009

```text
$.openshiftResources
```

- Uses: 8 occurrences in 8 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q010

```text
$.openshiftResources[?path=="/observability/aws-resource-exporter/prometheusrules/aws-resource-exporter-templated.prometheusrules.yaml.j2"].variables.aws_resources_exporter_instances
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'path'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["openshiftResources"][?(@["path"] == "/observability/aws-resource-exporter/prometheusrules/aws-resource-exporter-templated.prometheusrules.yaml.j2")]["variables"]["aws_resources_exporter_instances"]
```

- Candidate parser: accepted.

### Q011

```text
$.openshiftResources[?path=="/observability/cloudwatch-exporter/prometheusrules/cloudwatch-exporter-templated.prometheusrules.yaml.j2"].variables.accounts_with_cloudwatch_exporter
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'path'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["openshiftResources"][?(@["path"] == "/observability/cloudwatch-exporter/prometheusrules/cloudwatch-exporter-templated.prometheusrules.yaml.j2")]["variables"]["accounts_with_cloudwatch_exporter"]
```

- Candidate parser: accepted.

### Q012

```text
$.openshiftResources[?path=="/observability/cloudwatch-exporter/prometheusrules/cloudwatch-exporter-templated.prometheusrules.yaml.j2"].variables.cloudwatch_exporter_instances
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'path'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["openshiftResources"][?(@["path"] == "/observability/cloudwatch-exporter/prometheusrules/cloudwatch-exporter-templated.prometheusrules.yaml.j2")]["variables"]["cloudwatch_exporter_instances"]
```

- Candidate parser: accepted.

### Q013

```text
$.owner.'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["owner"]["$ref"]
```

- Candidate parser: accepted.

### Q014

```text
$.path
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q015

```text
$.peering.connections
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q016

```text
$.records
```

- Uses: 4 occurrences in 4 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q017

```text
$.resourceTemplates
```

- Uses: 8 occurrences in 8 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q018

```text
$.resourceTemplates[0].targets
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q019

```text
$.resourceTemplates[?(@.name=="rhobs-logs-event-collector")].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q020

```text
$.resourceTemplates[?(@.name=="rhobs-logs-forwarder")].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q021

```text
$.resourceTemplates[?(@.name=="rhobs-logs-token-refresher")].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q022

```text
$.resourceTemplates[?name=="aws-resource-exporter"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "aws-resource-exporter")]["targets"]
```

- Candidate parser: accepted.

### Q023

```text
$.resourceTemplates[?name=="cloudwatch-exporter"].targets
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "cloudwatch-exporter")]["targets"]
```

- Candidate parser: accepted.

### Q024

```text
$.resourceTemplates[?name=="clowder"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "clowder")]["targets"]
```

- Candidate parser: accepted.

### Q025

```text
$.resourceTemplates[?name=="clowder-env"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "clowder-env")]["targets"]
```

- Candidate parser: accepted.

### Q026

```text
$.resourceTemplates[?name=="clowder-plugin"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "clowder-plugin")]["targets"]
```

- Candidate parser: accepted.

### Q027

```text
$.resourceTemplates[?name=="costmanagement"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "costmanagement")]["targets"]
```

- Candidate parser: accepted.

### Q028

```text
$.resourceTemplates[?name=="event-router"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "event-router")]["targets"]
```

- Candidate parser: accepted.

### Q029

```text
$.resourceTemplates[?name=="monitoring-stack"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "monitoring-stack")]["targets"]
```

- Candidate parser: accepted.

### Q030

```text
$.resourceTemplates[?name=="netobserv"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "netobserv")]["targets"]
```

- Candidate parser: accepted.

### Q031

```text
$.resourceTemplates[?name=="nginx-proxy"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "nginx-proxy")]["targets"]
```

- Candidate parser: accepted.

### Q032

```text
$.resourceTemplates[?name=="rhobs-loki-object-store"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "rhobs-loki-object-store")]["targets"]
```

- Candidate parser: accepted.

### Q033

```text
$.resourceTemplates[?name=="rhobs-object-store"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "rhobs-object-store")]["targets"]
```

- Candidate parser: accepted.

### Q034

```text
$.resourceTemplates[?name=="thanos-querier"].targets
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'name'.
- Review: filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(@["name"] == "thanos-querier")]["targets"]
```

- Candidate parser: accepted.

### Q035

```text
$.roles
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q036

```text
$.self_service[?change_type.'$ref'=='/app-interface/changetype/cluster-auto-updater.yml'].datafiles
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected 'change_type'.
- Review: quoted dotted name; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["self_service"][?(@["change_type"]["$ref"] == "/app-interface/changetype/cluster-auto-updater.yml")]["datafiles"]
```

- Candidate parser: accepted.

### Q037

```text
$.signoffManagers[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["signoffManagers"][*]["$ref"]
```

- Candidate parser: accepted.

### Q038

```text
$.sponsors[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["sponsors"][*]["$ref"]
```

- Candidate parser: accepted.

### Q039

```text
$.users[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["users"][*]["$ref"]
```

- Candidate parser: accepted.

### Q040

```text
$.variables.name
```

- Uses: 4 occurrences in 4 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q041

```text
$.variables.region
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q042

```text
access
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q043

```text
accessTokenClientSecret.version
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q044

```text
accessTokenUrl
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q045

```text
access[*].cluster.'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["access"][*]["cluster"]["$ref"]
```

- Candidate parser: accepted.

### Q046

```text
access[?(@.cluster.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["access"][?(@["cluster"]["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q047

```text
account.'$ref'
```

- Uses: 9 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["account"]["$ref"]
```

- Candidate parser: accepted.

### Q048

```text
addonManagedUpgrades
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q049

```text
addonUpgradeTests
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q050

```text
address
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q051

```text
alertmanagerUrl
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q052

```text
allocated_storage
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q053

```text
allow_major_version_upgrade
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q054

```text
app
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q055

```text
app.'$ref'
```

- Uses: 9 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["app"]["$ref"]
```

- Candidate parser: accepted.

### Q056

```text
appCode
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q057

```text
apps[?@.onboardingStatus!="OnBoarded"]
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q058

```text
architectureDocument
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q059

```text
arguments
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q060

```text
arguments[*].namespace.'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["arguments"][*]["namespace"]["$ref"]
```

- Candidate parser: accepted.

### Q061

```text
automationToken
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q062

```text
aws_username
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q063

```text
backup_window
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q064

```text
blockedVersions
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q065

```text
channels
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q066

```text
channels.jiraBoard[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["channels"]["jiraBoard"][*]["$ref"]
```

- Candidate parser: accepted.

### Q067

```text
channels.jiraBoard[?(@.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["channels"]["jiraBoard"][?(@["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q068

```text
channels.jiraComponents
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q069

```text
channels.nextEscalationPolicy
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q070

```text
channels.nextEscalationPolicy.'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["channels"]["nextEscalationPolicy"]["$ref"]
```

- Candidate parser: accepted.

### Q071

```text
cloudflare_user
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q072

```text
cluster
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q073

```text
cluster.'$ref'
```

- Uses: 9 occurrences in 4 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["cluster"]["$ref"]
```

- Candidate parser: accepted.

### Q074

```text
clusterAdminAutomationToken
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q075

```text
codeComponents
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q076

```text
codeComponents[*].blockedVersions
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q077

```text
codeComponents[*].hotfixVersions
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q078

```text
config
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q079

```text
config_path
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q080

```text
connection_borrow_timeout
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q081

```text
consoleUrl
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q082

```text
cors_rules
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q083

```text
costCenter
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q084

```text
db_instance_identifier
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q085

```text
debug_logging
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q086

```text
delete
```

- Uses: 4 occurrences in 4 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q087

```text
deletionApprovals
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q088

```text
deletion_protection
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q089

```text
dependencies
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q090

```text
deployResources
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q091

```text
description
```

- Uses: 14 occurrences in 13 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q092

```text
disable
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q093

```text
disable.integrations
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q094

```text
displayName
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q095

```text
distribution_config
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q096

```text
elbFQDN
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q097

```text
enabled_cloudwatch_logs_exports
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q098

```text
endPoints
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q099

```text
engine_family
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q100

```text
engine_version
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q101

```text
environment
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q102

```text
escalationPolicy
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q103

```text
escalationPolicy.'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["escalationPolicy"]["$ref"]
```

- Candidate parser: accepted.

### Q104

```text
expirationDate
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q105

```text
externalResources
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q106

```text
externalResources[*].provisioner.'$ref'
```

- Uses: 4 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["externalResources"][*]["provisioner"]["$ref"]
```

- Candidate parser: accepted.

### Q107

```text
externalResources[*].resources
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q108

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="alb")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q109

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="asg")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q110

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="asg")].defaults
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q111

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="elasticache")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q112

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="elasticache")].defaults
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q113

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q114

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].blue_green_deployment
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q115

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].blue_green_deployment.target.parameter_group
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q116

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].defaults
```

- Uses: 6 occurrences in 4 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q117

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].overrides.allow_major_version_upgrade
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q118

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].overrides.instance_class
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q119

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].overrides.multi_az
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q120

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].overrides.snapshot_identifier
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q121

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds")].parameter_group
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q122

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds-proxy")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q123

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="rds-proxy")].defaults
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q124

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="s3")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q125

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="s3")].defaults
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q126

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="s3-cloudfront")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q127

```text
externalResources[?(@.provider=="aws")].resources[?(@.provider=="s3-cloudfront")].defaults
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q128

```text
externalResources[?(@.provisioner.'$ref'=='{{ ctx_file_path }}')].provider
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["externalResources"][?(@["provisioner"]["$ref"] == "{{ ctx_file_path }}")]["provider"]
```

- Candidate parser: accepted.

### Q129

```text
externalResources[?(@.provisioner.'$ref'=='{{ ctx_file_path }}')].provisioner
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["externalResources"][?(@["provisioner"]["$ref"] == "{{ ctx_file_path }}")]["provisioner"]
```

- Candidate parser: accepted.

### Q130

```text
externalResources[?(@.provisioner.'$ref'=='{{ ctx_file_path }}')].resources[?(@.provider!="rds" & @.provider!="elasticache" & @.provider!="asg" & @.provider!="alb" & @.provider!="s3" & @.provider!="s3-cloudfront" & @.provider!="rds-proxy")]
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: single conjunction; quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["externalResources"][?(@["provisioner"]["$ref"] == "{{ ctx_file_path }}")]["resources"][?(@["provider"] != "rds" && @["provider"] != "elasticache" && @["provider"] != "asg" && @["provider"] != "alb" && @["provider"] != "s3" && @["provider"] != "s3-cloudfront" && @["provider"] != "rds-proxy")]
```

- Candidate parser: accepted.

### Q131

```text
forceRerunTimestamp
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q132

```text
github_username
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q133

```text
glitchtipProjects
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q134

```text
glitchtip_teams
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q135

```text
grafanaUrl
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q136

```text
grafanaUrls
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q137

```text
iam_role_force_detach_policies
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q138

```text
iam_role_max_session_duration
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q139

```text
idle_client_timeout
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q140

```text
image
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q141

```text
imagePatterns
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q142

```text
images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q143

```text
inheritVersionData
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q144

```text
init_query
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q145

```text
instance
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q146

```text
instance_class
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q147

```text
instances
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q148

```text
instances[*].$
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; root reset; manual decision.
- Rewrite: manual: root-reset suffix is conditional and can duplicate root matches; do not replace blindly with $.

### Q149

```text
instances[*].identifier
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q150

```text
instances[*].namespace.'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["instances"][*]["namespace"]["$ref"]
```

- Candidate parser: accepted.

### Q151

```text
iops
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q152

```text
issueFields
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q153

```text
issueReopenState
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q154

```text
issueResolveState
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q155

```text
issueType
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q156

```text
items
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q157

```text
labels
```

- Uses: 13 occurrences in 12 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q158

```text
ldapGroup
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q159

```text
lifecycle_rules
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q160

```text
limitRanges
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q161

```text
log_group_retention_in_days
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q162

```text
machinePools
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q163

```text
maintenance_window
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q164

```text
managedResourceNames
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q165

```text
managedResourceTypes
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q166

```text
managedRoles
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q167

```text
managed[*].spec
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q168

```text
max_allocated_storage
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q169

```text
max_connections_percent
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q170

```text
max_idle_connections_percent
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q171

```text
multi_az
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q172

```text
multi_az_enabled
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q173

```text
name
```

- Uses: 9 occurrences in 8 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q174

```text
namespace.'$ref'
```

- Uses: 4 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"]["$ref"]
```

- Candidate parser: accepted.

### Q175

```text
namespace[?(@.cluster.name=~"backplanei.*" & @.environment.name=~".*integration.*" & @.name=="dynatrace")]
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "backplanei.*") && search(@["environment"]["name"], ".*integration.*") && @["name"] == "dynatrace")]
```

- Candidate parser: accepted.

### Q176

```text
namespace[?(@.cluster.name=~"backplanep.*" & @.environment.name=~".*prod.*" & @.name=="dynatrace")]
```

- Uses: 7 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "backplanep.*") && search(@["environment"]["name"], ".*prod.*") && @["name"] == "dynatrace")]
```

- Candidate parser: accepted.

### Q177

```text
namespace[?(@.cluster.name=~"backplanep.*" & @.environment.name=~".*production.*" & @.name=="dynatrace")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "backplanep.*") && search(@["environment"]["name"], ".*production.*") && @["name"] == "dynatrace")]
```

- Candidate parser: accepted.

### Q178

```text
namespace[?(@.cluster.name=~"backplanes.*" & @.environment.name=~".*stage.*" & @.name=="dynatrace")]
```

- Uses: 3 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "backplanes.*") && search(@["environment"]["name"], ".*stage.*") && @["name"] == "dynatrace")]
```

- Candidate parser: accepted.

### Q179

```text
namespace[?(@.cluster.name=~"hive.*" & @.environment.name=~".*integration.*" & @.name=="cluster-scope")]
```

- Uses: 8 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && search(@["environment"]["name"], ".*integration.*") && @["name"] == "cluster-scope")]
```

- Candidate parser: accepted.

### Q180

```text
namespace[?(@.cluster.name=~"hive.*" & @.environment.name=~".*production.*" & @.name=="cluster-scope")]
```

- Uses: 15 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && search(@["environment"]["name"], ".*production.*") && @["name"] == "cluster-scope")]
```

- Candidate parser: accepted.

### Q181

```text
namespace[?(@.cluster.name=~"hive.*" & @.environment.name=~".*stage.*" & @.name=="cluster-scope")]
```

- Uses: 11 occurrences in 6 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && search(@["environment"]["name"], ".*stage.*") && @["name"] == "cluster-scope")]
```

- Candidate parser: accepted.

### Q182

```text
namespace[?(@.cluster.name=~"hive.*" & @.name=="osd-fleet-manager-integration")]
```

- Uses: 21 occurrences in 10 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && @["name"] == "osd-fleet-manager-integration")]
```

- Candidate parser: accepted.

### Q183

```text
namespace[?(@.cluster.name=~"hive.*" & @.name=="osd-fleet-manager-production")]
```

- Uses: 182 occurrences in 10 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q184

```text
namespace[?(@.cluster.name=~"hive.*" & @.name=="osd-fleet-manager-stage")]
```

- Uses: 60 occurrences in 6 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hive.*") && @["name"] == "osd-fleet-manager-stage")]
```

- Candidate parser: accepted.

### Q185

```text
namespace[?(@.cluster.name=~"hivei01ue1" & @.name=="osd-fleet-manager-integration")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivei01ue1") && @["name"] == "osd-fleet-manager-integration")]
```

- Candidate parser: accepted.

### Q186

```text
namespace[?(@.cluster.name=~"hivep01ue1" & @.name=="osd-fleet-manager-production")]
```

- Uses: 12 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep01ue1") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q187

```text
namespace[?(@.cluster.name=~"hivep04ew2" & @.name=="osd-fleet-manager-production")]
```

- Uses: 12 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep04ew2") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q188

```text
namespace[?(@.cluster.name=~"hivep05ue1" & @.name=="osd-fleet-manager-production")]
```

- Uses: 6 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep05ue1") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q189

```text
namespace[?(@.cluster.name=~"hivep06uw2" & @.name=="osd-fleet-manager-production")]
```

- Uses: 12 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep06uw2") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q190

```text
namespace[?(@.cluster.name=~"hivep07ue2" & @.name=="osd-fleet-manager-production")]
```

- Uses: 7 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep07ue2") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q191

```text
namespace[?(@.cluster.name=~"hivep08ue2" & @.name=="osd-fleet-manager-production")]
```

- Uses: 12 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "hivep08ue2") && @["name"] == "osd-fleet-manager-production")]
```

- Candidate parser: accepted.

### Q192

```text
namespace[?(@.cluster.name=~"{{ static.hive_cluster_pattern | default('hive.*') }}" & @.name=="osd-fleet-manager-{{ static.environment }}")]
```

- Uses: 5 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["cluster"]["name"], "{{ static.hive_cluster_pattern | default('hive.*') }}") && @["name"] == "osd-fleet-manager-{{ static.environment }}")]
```

- Candidate parser: accepted.

### Q193

```text
namespace[?(@.environment.name=="App-SRE-stage" & @.name=~"selector-syncset-demo.*")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(@["environment"]["name"] == "App-SRE-stage" && search(@["name"], "selector-syncset-demo.*"))]
```

- Candidate parser: accepted.

### Q194

```text
namespace[?(@.environment.name=~"integration.*" & @.name=="cluster-scope")]
```

- Uses: 4 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: regex semantics; single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(search(@["environment"]["name"], "integration.*") && @["name"] == "cluster-scope")]
```

- Candidate parser: accepted.

### Q195

```text
namespace[?(@.name=="acs-secure-services" & (@.environment.labels.type!="production"))]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(@["name"] == "acs-secure-services" && @["environment"]["labels"]["type"] != "production")]
```

- Candidate parser: accepted.

### Q196

```text
namespace[?(@.name=="acs-secure-services" & @.environment.labels.type=="production")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(@["name"] == "acs-secure-services" && @["environment"]["labels"]["type"] == "production")]
```

- Candidate parser: accepted.

### Q197

```text
namespace[?(@.name=="cert-manager" & (@.environment.labels.type!="production"))]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(@["name"] == "cert-manager" && @["environment"]["labels"]["type"] != "production")]
```

- Candidate parser: accepted.

### Q198

```text
namespace[?(@.name=="cert-manager" & (@.environment.labels.type=="production"))]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: unexpected '('.
- Review: single conjunction; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["namespace"][?(@["name"] == "cert-manager" && @["environment"]["labels"]["type"] == "production")]
```

- Candidate parser: accepted.

### Q199

```text
network.type
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q200

```text
networkPoliciesAllow
```

- Uses: 4 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q201

```text
notifications
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q202

```text
onboardingStatus
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q203

```text
openshiftResources
```

- Uses: 3 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q204

```text
openshiftResources[*].managedSsoClient.'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["openshiftResources"][*]["managedSsoClient"]["$ref"]
```

- Candidate parser: accepted.

### Q205

```text
openshiftResources[?(@.path=="/observability/prometheusrules/osd-fleet-manager-nonprod.prometheusrules.yaml.j2")].variables.sectors
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q206

```text
openshiftResources[?(@.path=="/services/ocm/aws-sts-policies.configmap.yaml")].variables
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q207

```text
openshiftResources[?(@.path=="/services/ocm/gcp-wif-templates.configmap.yaml")].variables
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q208

```text
openshiftResources[?(@.provider=="managed-sso-client" & @.managedSsoClient.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: single conjunction; quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["openshiftResources"][?(@["provider"] == "managed-sso-client" && @["managedSsoClient"]["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q209

```text
openshiftResources[?(@.provider=="managed-sso-client")].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q210

```text
openshiftResources[?(@.provider=="resource")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q211

```text
openshiftResources[?(@.provider=="resource")].path
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q212

```text
openshiftResources[?(@.provider=="resource-template")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q213

```text
openshiftResources[?(@.provider=="resource-template")].variables
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q214

```text
openshiftResources[?(@.provider=="rhcs-cert")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q215

```text
openshiftResources[?(@.provider=="route")]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q216

```text
openshiftResources[?(@.provider=="route")].vault_tls_secret_version
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q217

```text
openshiftResources[?(@.provider=="vault-secret")].annotations
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q218

```text
openshiftResources[?(@.provider=="vault-secret")].labels
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q219

```text
openshiftResources[?(@.provider=="vault-secret")].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q220

```text
openshiftResources[?(@.provider=="vault-secret")].version
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q221

```text
org_username
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q222

```text
owner
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q223

```text
pagerduty_username
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q224

```text
parameter_group_name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q225

```text
parameters
```

- Uses: 6 occurrences in 6 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q226

```text
parentApp.'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["parentApp"]["$ref"]
```

- Candidate parser: accepted.

### Q227

```text
performance_insights_enabled
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q228

```text
permissions[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["permissions"][*]["$ref"]
```

- Candidate parser: accepted.

### Q229

```text
permissions[?(@.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["permissions"][?(@["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q230

```text
projectRequests[*].projects
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q231

```text
prometheusUrl
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q232

```text
promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q233

```text
promotion.promotion_data
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q234

```text
public_gpg_key
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q235

```text
publishVersionData
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q236

```text
quayRepos[*].items
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q237

```text
quayRepos[*].items[*].mirror.'ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["quayRepos"][*]["items"][*]["mirror"]["ref"]
```

- Candidate parser: accepted.

### Q238

```text
quayRepos[*].teams[*].permissions[*].'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["quayRepos"][*]["teams"][*]["permissions"][*]["$ref"]
```

- Candidate parser: accepted.

### Q239

```text
quayRepos[*].teams[*].permissions[?(@.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["quayRepos"][*]["teams"][*]["permissions"][?(@["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q240

```text
quay_username
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q241

```text
queries[*].path
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q242

```text
quota
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q243

```text
records
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q244

```text
ref
```

- Uses: 5 occurrences in 5 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q245

```text
requireFips
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q246

```text
require_tls
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q247

```text
resetPasswords
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q248

```text
resourceTemplates
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q249

```text
resourceTemplates[*].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q250

```text
resourceTemplates[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q251

```text
resourceTemplates[*].parameters
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q252

```text
resourceTemplates[*].parameters.CONTROL_PLANE_LOG_BUCKET_ID
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q253

```text
resourceTemplates[*].parameters.CONTROL_PLANE_LOG_PROJECT_NAME
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q254

```text
resourceTemplates[*].parameters.CONTROL_PLANE_LOG_S3_WRITER_ROLE_ARN
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q255

```text
resourceTemplates[*].parameters.ENABLE_HCP_CONTROL_PLANE_LOG
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q256

```text
resourceTemplates[*].parameters.HYPERSHIFT_OPERATOR_OVERRIDING_DATA
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q257

```text
resourceTemplates[*].parameters.OPENSHIFT_LOGGING_VECTOR_IMAGE_PATH
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q258

```text
resourceTemplates[*].parameters.VECTOR_PIPELINE_CONFIG
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q259

```text
resourceTemplates[*].path
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q260

```text
resourceTemplates[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q261

```text
resourceTemplates[*].targets[*]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q262

```text
resourceTemplates[*].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q263

```text
resourceTemplates[*].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q264

```text
resourceTemplates[*].targets[*].images
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q265

```text
resourceTemplates[*].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q266

```text
resourceTemplates[*].targets[*].namespace.'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][*]["targets"][*]["namespace"]["$ref"]
```

- Candidate parser: accepted.

### Q267

```text
resourceTemplates[*].targets[*].parameters
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q268

```text
resourceTemplates[*].targets[*].parameters.CONTROL_PLANE_LOG_BUCKET_ID
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q269

```text
resourceTemplates[*].targets[*].parameters.CONTROL_PLANE_LOG_PROJECT_NAME
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q270

```text
resourceTemplates[*].targets[*].parameters.CONTROL_PLANE_LOG_S3_WRITER_ROLE_ARN
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q271

```text
resourceTemplates[*].targets[*].parameters.ENABLE_HCP_CONTROL_PLANE_LOG
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q272

```text
resourceTemplates[*].targets[*].parameters.HYPERSHIFT_OPERATOR_OVERRIDING_DATA
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q273

```text
resourceTemplates[*].targets[*].parameters.OPENSHIFT_LOGGING_VECTOR_IMAGE_PATH
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q274

```text
resourceTemplates[*].targets[*].parameters.VECTOR_PIPELINE_CONFIG
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q275

```text
resourceTemplates[*].targets[*].promotion
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q276

```text
resourceTemplates[*].targets[*].promotion.promotion_data
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q277

```text
resourceTemplates[*].targets[*].ref
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q278

```text
resourceTemplates[*].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q279

```text
resourceTemplates[*].targets[*].upstream
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q280

```text
resourceTemplates[*].targets[?(@.namespace.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][*]["targets"][?(@["namespace"]["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q281

```text
resourceTemplates[?(@.name == "insights-dashboard")].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q282

```text
resourceTemplates[?(@.name == "insights-dashboard")].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q283

```text
resourceTemplates[?(@.name == "insights-dashboard")].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q284

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q285

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q286

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q287

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q288

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q289

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q290

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].ref
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q291

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q292

```text
resourceTemplates[?(@.name == "insights-dashboard")].targets[*].upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q293

```text
resourceTemplates[?(@.name == "patchman-ui")].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q294

```text
resourceTemplates[?(@.name == "patchman-ui")].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q295

```text
resourceTemplates[?(@.name == "patchman-ui")].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q296

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q297

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q298

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q299

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q300

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q301

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q302

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].ref
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q303

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q304

```text
resourceTemplates[?(@.name == "patchman-ui")].targets[*].upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q305

```text
resourceTemplates[?(@.name == "registration-assistant")].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q306

```text
resourceTemplates[?(@.name == "registration-assistant")].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q307

```text
resourceTemplates[?(@.name == "registration-assistant")].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q308

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q309

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q310

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q311

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q312

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q313

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q314

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].ref
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q315

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q316

```text
resourceTemplates[?(@.name == "registration-assistant")].targets[*].upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q317

```text
resourceTemplates[?(@.name == "vulnerability-ui")].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q318

```text
resourceTemplates[?(@.name == "vulnerability-ui")].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q319

```text
resourceTemplates[?(@.name == "vulnerability-ui")].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: filter comparison/existence.

### Q320

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q321

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q322

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q323

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q324

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q325

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q326

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].ref
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q327

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q328

```text
resourceTemplates[?(@.name == "vulnerability-ui")].targets[*].upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; filter comparison/existence.

### Q329

```text
resourceTemplates[?(@.name =~ ".*-frontend")].hash_length
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["hash_length"]
```

- Candidate parser: accepted.

### Q330

```text
resourceTemplates[?(@.name =~ ".*-frontend")].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["parameters"]
```

- Candidate parser: accepted.

### Q331

```text
resourceTemplates[?(@.name =~ ".*-frontend")].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["secretParameters"]
```

- Candidate parser: accepted.

### Q332

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].delete
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["delete"]
```

- Candidate parser: accepted.

### Q333

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].disable
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["disable"]
```

- Candidate parser: accepted.

### Q334

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].images
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["images"]
```

- Candidate parser: accepted.

### Q335

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].name
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["name"]
```

- Candidate parser: accepted.

### Q336

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].parameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["parameters"]
```

- Candidate parser: accepted.

### Q337

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].promotion
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["promotion"]
```

- Candidate parser: accepted.

### Q338

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].ref
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["ref"]
```

- Candidate parser: accepted.

### Q339

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].secretParameters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["secretParameters"]
```

- Candidate parser: accepted.

### Q340

```text
resourceTemplates[?(@.name =~ ".*-frontend")].targets[*].upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type; regex semantics; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["resourceTemplates"][?(search(@["name"], ".*-frontend"))]["targets"][*]["upstream"]
```

- Candidate parser: accepted.

### Q341

```text
resources[*].path
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q342

```text
roles[*]
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q343

```text
roles[*].'$ref'
```

- Uses: 6 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["roles"][*]["$ref"]
```

- Candidate parser: accepted.

### Q344

```text
roles[?(@.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 6 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["roles"][?(@["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q345

```text
schedule
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q346

```text
secretParameters
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q347

```text
secretParameters[*].version
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: array wildcard; check input type.

### Q348

```text
sectors
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q349

```text
self_service
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q350

```text
server.'$ref'
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["server"]["$ref"]
```

- Candidate parser: accepted.

### Q351

```text
serverUrl
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q352

```text
serviceOwners
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q353

```text
session_pinning_filters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q354

```text
sharedResources
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q355

```text
signoffManagers
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q356

```text
slack
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q357

```text
some.paths
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q358

```text
sopsUrl
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q359

```text
spec.config.receivers
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q360

```text
spec.external_id
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q361

```text
spec.id
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q362

```text
spec.oidc_endpoint_url
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q363

```text
spec.provision_shard_id
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q364

```text
spec.version
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q365

```text
sponsors
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q366

```text
storage_type
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q367

```text
supportedDeploymentRegions
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q368

```text
tag_on_cluster_updates
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q369

```text
tag_on_merge_requests
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q370

```text
tfVersion
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q371

```text
timeout
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q372

```text
type
```

- Uses: 3 occurrences in 3 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q373

```text
unleash.projects[*].'$ref'
```

- Uses: 2 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["unleash"]["projects"][*]["$ref"]
```

- Candidate parser: accepted.

### Q374

```text
upgradePolicyAllowedMutexes
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q375

```text
upgradePolicyAllowedWorkloads
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q376

```text
upgradePolicyClusters
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q377

```text
upgradePolicyDefaults
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q378

```text
upstream
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q379

```text
uri
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q380

```text
use_channel_in_image_tag
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q381

```text
user_policies[*].'$ref'
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: array wildcard; check input type; quoted dotted name.
- Candidate rewrite (syntax-tested only):

```text
$["user_policies"][*]["$ref"]
```

- Candidate parser: accepted.

### Q382

```text
user_policies[?(@.'$ref'=='{{ ctx_file_path }}')]
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: JSONPathSyntaxError: expected a shorthand selector.
- Review: quoted dotted name; templated expression; filter comparison/existence.
- Candidate rewrite (syntax-tested only):

```text
$["user_policies"][?(@["$ref"] == "{{ ctx_file_path }}")]
```

- Candidate parser: accepted.

### Q383

```text
users
```

- Uses: 1 occurrences in 1 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q384

```text
variables
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

### Q385

```text
workaround
```

- Uses: 2 occurrences in 2 files.
- Legacy parser: accepted.
- Target parser: accepted.
- Review: ordinary selection; still verify values and locations.

## File-by-file occurrence index

Paths below are relative to the app-interface checkout. Fields include list indexes and embedded-YAML markers. Line numbers describe this exact snapshot.

### `data/app-interface/changetype/add-permission-member.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q229  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q228  |
|   26 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q239  |
|   28 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q238  |

### `data/app-interface/changetype/alb-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q108  |

### `data/app-interface/changetype/app-owner-saas-file-target-approver.yml`

| Line | Field                                    | Category / source                 | Query |
| ---: | ---------------------------------------- | --------------------------------- | ----- |
|   21 | <code>changes[0].context.selector</code> | ownership context / configuration | Q055  |

### `data/app-interface/changetype/app-owner.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   25 | <code>changes[0].context.selector</code>      | ownership context / configuration    | Q055  |
|   31 | <code>changes[1].context.selector</code>      | ownership context / configuration    | Q055  |
|   34 | <code>changes[2].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q157  |
|   35 | <code>changes[2].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q091  |
|   36 | <code>changes[2].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q352  |
|   37 | <code>changes[2].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q075  |
|   38 | <code>changes[2].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q102  |
|   39 | <code>changes[2].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q358  |
|   40 | <code>changes[2].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q058  |
|   41 | <code>changes[2].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q136  |
|   42 | <code>changes[2].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q098  |
|   43 | <code>changes[2].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q056  |
|   44 | <code>changes[2].jsonPathSelectors[10]</code> | change-type selector / configuration | Q083  |
|   50 | <code>changes[3].context.selector</code>      | ownership context / configuration    | Q055  |
|   56 | <code>changes[4].context.selector</code>      | ownership context / configuration    | Q055  |
|   63 | <code>changes[5].context.selector</code>      | ownership context / configuration    | Q055  |
|   69 | <code>changes[6].context.selector</code>      | ownership context / configuration    | Q055  |

### `data/app-interface/changetype/app-quay-repos-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q156  |

### `data/app-interface/changetype/asg-defaults-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/asg-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q109  |
|   24 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q110  |

### `data/app-interface/changetype/automated-action-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q372  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q091  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q059  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q157  |

### `data/app-interface/changetype/aws-account-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   22 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q367  |
|   23 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q092  |
|   27 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q130  |
|   29 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q106  |
|   33 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q128  |
|   34 | <code>changes[2].jsonPathSelectors[1]</code> | change-type selector / configuration | Q129  |
|   36 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q106  |
|   41 | <code>changes[3].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   43 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q047  |
|   47 | <code>changes[4].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   49 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q047  |
|   54 | <code>changes[5].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   56 | <code>changes[5].context.selector</code>     | ownership context / configuration    | Q047  |
|   60 | <code>changes[6].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   62 | <code>changes[6].context.selector</code>     | ownership context / configuration    | Q047  |
|   67 | <code>changes[7].jsonPathSelectors[0]</code> | change-type selector / configuration | Q130  |
|   69 | <code>changes[7].context.selector</code>     | ownership context / configuration    | Q106  |
|   73 | <code>changes[8].jsonPathSelectors[0]</code> | change-type selector / configuration | Q128  |
|   74 | <code>changes[8].jsonPathSelectors[1]</code> | change-type selector / configuration | Q129  |
|   76 | <code>changes[8].context.selector</code>     | ownership context / configuration    | Q106  |
|   83 | <code>changes[9].context.selector</code>     | ownership context / configuration    | Q116  |
|   89 | <code>changes[10].context.selector</code>    | ownership context / configuration    | Q116  |
|   95 | <code>changes[11].context.selector</code>    | ownership context / configuration    | Q047  |
|  100 | <code>changes[12].context.selector</code>    | ownership context / configuration    | Q047  |

### `data/app-interface/changetype/aws-deletion-approvals.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q087  |

### `data/app-interface/changetype/aws-password-reset.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q247  |

### `data/app-interface/changetype/aws-region-enabler.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q367  |

### `data/app-interface/changetype/bot-owner.yml`

| Line | Field                                              | Category / source                    | Query |
| ---: | -------------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / configuration | Q157  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / configuration | Q173  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>       | change-type selector / configuration | Q091  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>       | change-type selector / configuration | Q222  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>       | change-type selector / configuration | Q240  |
|   26 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / configuration   | Q013  |

### `data/app-interface/changetype/breakglass-role-manager.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q344  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q343  |

### `data/app-interface/changetype/change-log/app-change-log-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/app-metadata.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q157  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q091  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q058  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q358  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q136  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q202  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code> | change-type selector / configuration | Q352  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code> | change-type selector / configuration | Q089  |

### `data/app-interface/changetype/change-log/app-monitoring.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q098  |

### `data/app-interface/changetype/change-log/change-type-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/cloudflare-dns-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/cluster-disable-integrations.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q093  |

### `data/app-interface/changetype/change-log/cluster-ovn-migration.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q199  |

### `data/app-interface/changetype/change-log/cluster-upgrade.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q364  |

### `data/app-interface/changetype/change-log/dns-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/docs.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q385  |

### `data/app-interface/changetype/change-log/gabi-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/glitchtip-project-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/hack.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q385  |

### `data/app-interface/changetype/change-log/integration-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/jenkins-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/namespace-external-resources-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q105  |

### `data/app-interface/changetype/change-log/namespace-network-policy-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q200  |

### `data/app-interface/changetype/change-log/namespace-openshift-resources-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q203  |

### `data/app-interface/changetype/change-log/namespace-vault-secret-promotion.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q220  |

### `data/app-interface/changetype/change-log/progressive-delivery.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q275  |

### `data/app-interface/changetype/change-log/resource-parameter-group-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/resource-rds-defaults-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/resource-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/role-access-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q042  |

### `data/app-interface/changetype/change-log/role-self-service-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q349  |

### `data/app-interface/changetype/change-log/saas-file-image.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q141  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q279  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q264  |

### `data/app-interface/changetype/change-log/saas-file-managed-resource-types.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q165  |

### `data/app-interface/changetype/change-log/saas-file-parameters.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q225  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q251  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q267  |

### `data/app-interface/changetype/change-log/saas-file-promotion.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q277  |

### `data/app-interface/changetype/change-log/saas-file-target-parameters.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q225  |

### `data/app-interface/changetype/change-log/saas-file-target-promotion.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q244  |

### `data/app-interface/changetype/change-log/schedule-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/score-card-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/slo-document-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/sre-checkpoint-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/user-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-log/vault-policy-updates.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/change-type-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/ci-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q089  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q075  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q236  |
|   24 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q173  |
|   25 | <code>changes[1].jsonPathSelectors[1]</code> | change-type selector / configuration | Q157  |
|   26 | <code>changes[1].jsonPathSelectors[2]</code> | change-type selector / configuration | Q091  |
|   27 | <code>changes[1].jsonPathSelectors[3]</code> | change-type selector / configuration | Q145  |
|   28 | <code>changes[1].jsonPathSelectors[4]</code> | change-type selector / configuration | Q372  |
|   29 | <code>changes[1].jsonPathSelectors[5]</code> | change-type selector / configuration | Q079  |
|   30 | <code>changes[1].jsonPathSelectors[6]</code> | change-type selector / configuration | Q078  |
|   32 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q055  |
|   38 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q055  |
|   44 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q237  |
|   50 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q237  |

### `data/app-interface/changetype/cluster-auto-updater.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q081  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q096  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q351  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q231  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q051  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q061  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q074  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q361  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q360  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q364  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q363  |
|   29 | <code>changes[0].jsonPathSelectors[11]</code> | change-type selector / configuration | Q362  |

### `data/app-interface/changetype/cluster-labels.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q157  |

### `data/app-interface/changetype/cluster-machine-pool-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q162  |

### `data/app-interface/changetype/cluster-owner-namespace-admin.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].context.selector</code>      | ownership context / configuration    | Q073  |
|   25 | <code>changes[1].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q157  |
|   26 | <code>changes[1].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q173  |
|   27 | <code>changes[1].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q091  |
|   28 | <code>changes[1].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q101  |
|   29 | <code>changes[1].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q135  |
|   30 | <code>changes[1].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q160  |
|   31 | <code>changes[1].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q242  |
|   32 | <code>changes[1].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q200  |
|   33 | <code>changes[1].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q166  |
|   34 | <code>changes[1].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q165  |
|   35 | <code>changes[1].jsonPathSelectors[10]</code> | change-type selector / configuration | Q203  |
|   36 | <code>changes[1].jsonPathSelectors[11]</code> | change-type selector / configuration | Q354  |
|   37 | <code>changes[1].jsonPathSelectors[12]</code> | change-type selector / configuration | Q107  |
|   39 | <code>changes[1].context.selector</code>      | ownership context / configuration    | Q073  |
|   43 | <code>changes[2].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q157  |
|   44 | <code>changes[2].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q173  |
|   45 | <code>changes[2].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q091  |
|   46 | <code>changes[2].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q072  |
|   47 | <code>changes[2].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q054  |
|   48 | <code>changes[2].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q101  |
|   49 | <code>changes[2].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q135  |
|   50 | <code>changes[2].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q160  |
|   51 | <code>changes[2].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q242  |
|   52 | <code>changes[2].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q200  |
|   53 | <code>changes[2].jsonPathSelectors[10]</code> | change-type selector / configuration | Q166  |
|   54 | <code>changes[2].jsonPathSelectors[11]</code> | change-type selector / configuration | Q165  |
|   55 | <code>changes[2].jsonPathSelectors[12]</code> | change-type selector / configuration | Q203  |
|   56 | <code>changes[2].jsonPathSelectors[13]</code> | change-type selector / configuration | Q354  |
|   57 | <code>changes[2].jsonPathSelectors[14]</code> | change-type selector / configuration | Q107  |
|   59 | <code>changes[2].context.selector</code>      | ownership context / configuration    | Q073  |
|   66 | <code>changes[3].context.selector</code>      | ownership context / configuration    | Q211  |

### `data/app-interface/changetype/cluster-owner-namespace-app-updater.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q054  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q073  |

### `data/app-interface/changetype/cluster-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   24 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q073  |
|   29 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q073  |
|   35 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q073  |
|   39 | <code>changes[3].jsonPathSelectors[0]</code> | change-type selector / configuration | Q046  |
|   41 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q045  |
|   45 | <code>changes[4].jsonPathSelectors[0]</code> | change-type selector / configuration | Q046  |
|   47 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q045  |

### `data/app-interface/changetype/container-image-mirror-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/dns-zone-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q243  |

### `data/app-interface/changetype/dynatrace-environment-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/elasticache-defaults-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q088  |
|   18 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q163  |
|   19 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q224  |
|   20 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q172  |

### `data/app-interface/changetype/elasticache-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q111  |
|   24 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q112  |

### `data/app-interface/changetype/environment-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q225  |

### `data/app-interface/changetype/escalation-policy-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q069  |
|   23 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q070  |
|   28 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q069  |
|   30 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q070  |
|   36 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q103  |
|   38 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q103  |
|   42 | <code>changes[3].jsonPathSelectors[0]</code> | change-type selector / configuration | Q157  |
|   43 | <code>changes[3].jsonPathSelectors[1]</code> | change-type selector / configuration | Q065  |

### `data/app-interface/changetype/external-user-sponsor.yml`

| Line | Field                                              | Category / source                    | Query |
| ---: | -------------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / configuration | Q157  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / configuration | Q173  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>       | change-type selector / configuration | Q132  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>       | change-type selector / configuration | Q240  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>       | change-type selector / configuration | Q365  |
|   26 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / configuration   | Q038  |

### `data/app-interface/changetype/gabi-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q147  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q148  |

### `data/app-interface/changetype/gabi-signoff-manager.yml`

| Line | Field                                              | Category / source                    | Query |
| ---: | -------------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / configuration | Q091  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / configuration | Q355  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>       | change-type selector / configuration | Q383  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>       | change-type selector / configuration | Q104  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>       | change-type selector / configuration | Q149  |
|   26 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / configuration   | Q037  |

### `data/app-interface/changetype/gabi-signoff-users.yml`

| Line | Field                                              | Category / source                    | Query |
| ---: | -------------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / configuration | Q091  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / configuration | Q149  |
|   23 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / configuration   | Q039  |

### `data/app-interface/changetype/gitlab-project-request-approver.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q230  |

### `data/app-interface/changetype/glitchtip-project-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/glitchtip-team-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/hierarchical-app-owner.yml`

| Line | Field                                    | Category / source                 | Query |
| ---: | ---------------------------------------- | --------------------------------- | ----- |
|   24 | <code>changes[0].context.selector</code> | ownership context / configuration | Q226  |

### `data/app-interface/changetype/hotfix-version-manager.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q077  |
|   22 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q076  |

### `data/app-interface/changetype/hypershift-operator-overriding-data-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q256  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q272  |

### `data/app-interface/changetype/integration-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/integration-contributor.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q167  |

### `data/app-interface/changetype/interact-owner.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q329  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q330  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q331  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q335  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q338  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q336  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q339  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q340  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q334  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q333  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q332  |
|   29 | <code>changes[0].jsonPathSelectors[11]</code> | change-type selector / configuration | Q337  |
|   31 | <code>changes[0].jsonPathSelectors[12]</code> | change-type selector / configuration | Q293  |
|   32 | <code>changes[0].jsonPathSelectors[13]</code> | change-type selector / configuration | Q294  |
|   33 | <code>changes[0].jsonPathSelectors[14]</code> | change-type selector / configuration | Q295  |
|   34 | <code>changes[0].jsonPathSelectors[15]</code> | change-type selector / configuration | Q299  |
|   35 | <code>changes[0].jsonPathSelectors[16]</code> | change-type selector / configuration | Q302  |
|   36 | <code>changes[0].jsonPathSelectors[17]</code> | change-type selector / configuration | Q300  |
|   37 | <code>changes[0].jsonPathSelectors[18]</code> | change-type selector / configuration | Q303  |
|   38 | <code>changes[0].jsonPathSelectors[19]</code> | change-type selector / configuration | Q304  |
|   39 | <code>changes[0].jsonPathSelectors[20]</code> | change-type selector / configuration | Q298  |
|   40 | <code>changes[0].jsonPathSelectors[21]</code> | change-type selector / configuration | Q297  |
|   41 | <code>changes[0].jsonPathSelectors[22]</code> | change-type selector / configuration | Q296  |
|   42 | <code>changes[0].jsonPathSelectors[23]</code> | change-type selector / configuration | Q301  |
|   44 | <code>changes[0].jsonPathSelectors[24]</code> | change-type selector / configuration | Q317  |
|   45 | <code>changes[0].jsonPathSelectors[25]</code> | change-type selector / configuration | Q318  |
|   46 | <code>changes[0].jsonPathSelectors[26]</code> | change-type selector / configuration | Q319  |
|   47 | <code>changes[0].jsonPathSelectors[27]</code> | change-type selector / configuration | Q323  |
|   48 | <code>changes[0].jsonPathSelectors[28]</code> | change-type selector / configuration | Q326  |
|   49 | <code>changes[0].jsonPathSelectors[29]</code> | change-type selector / configuration | Q324  |
|   50 | <code>changes[0].jsonPathSelectors[30]</code> | change-type selector / configuration | Q327  |
|   51 | <code>changes[0].jsonPathSelectors[31]</code> | change-type selector / configuration | Q328  |
|   52 | <code>changes[0].jsonPathSelectors[32]</code> | change-type selector / configuration | Q322  |
|   53 | <code>changes[0].jsonPathSelectors[33]</code> | change-type selector / configuration | Q321  |
|   54 | <code>changes[0].jsonPathSelectors[34]</code> | change-type selector / configuration | Q320  |
|   55 | <code>changes[0].jsonPathSelectors[35]</code> | change-type selector / configuration | Q325  |
|   57 | <code>changes[0].jsonPathSelectors[36]</code> | change-type selector / configuration | Q281  |
|   58 | <code>changes[0].jsonPathSelectors[37]</code> | change-type selector / configuration | Q282  |
|   59 | <code>changes[0].jsonPathSelectors[38]</code> | change-type selector / configuration | Q283  |
|   60 | <code>changes[0].jsonPathSelectors[39]</code> | change-type selector / configuration | Q287  |
|   61 | <code>changes[0].jsonPathSelectors[40]</code> | change-type selector / configuration | Q290  |
|   62 | <code>changes[0].jsonPathSelectors[41]</code> | change-type selector / configuration | Q288  |
|   63 | <code>changes[0].jsonPathSelectors[42]</code> | change-type selector / configuration | Q291  |
|   64 | <code>changes[0].jsonPathSelectors[43]</code> | change-type selector / configuration | Q292  |
|   65 | <code>changes[0].jsonPathSelectors[44]</code> | change-type selector / configuration | Q286  |
|   66 | <code>changes[0].jsonPathSelectors[45]</code> | change-type selector / configuration | Q285  |
|   67 | <code>changes[0].jsonPathSelectors[46]</code> | change-type selector / configuration | Q284  |
|   68 | <code>changes[0].jsonPathSelectors[47]</code> | change-type selector / configuration | Q289  |
|   70 | <code>changes[0].jsonPathSelectors[48]</code> | change-type selector / configuration | Q305  |
|   71 | <code>changes[0].jsonPathSelectors[49]</code> | change-type selector / configuration | Q306  |
|   72 | <code>changes[0].jsonPathSelectors[50]</code> | change-type selector / configuration | Q307  |
|   73 | <code>changes[0].jsonPathSelectors[51]</code> | change-type selector / configuration | Q311  |
|   74 | <code>changes[0].jsonPathSelectors[52]</code> | change-type selector / configuration | Q314  |
|   75 | <code>changes[0].jsonPathSelectors[53]</code> | change-type selector / configuration | Q312  |
|   76 | <code>changes[0].jsonPathSelectors[54]</code> | change-type selector / configuration | Q315  |
|   77 | <code>changes[0].jsonPathSelectors[55]</code> | change-type selector / configuration | Q316  |
|   78 | <code>changes[0].jsonPathSelectors[56]</code> | change-type selector / configuration | Q310  |
|   79 | <code>changes[0].jsonPathSelectors[57]</code> | change-type selector / configuration | Q309  |
|   80 | <code>changes[0].jsonPathSelectors[58]</code> | change-type selector / configuration | Q308  |
|   81 | <code>changes[0].jsonPathSelectors[59]</code> | change-type selector / configuration | Q313  |

### `data/app-interface/changetype/jenkins-config-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q173  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q157  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q091  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q145  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q372  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q079  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code> | change-type selector / configuration | Q078  |
|   30 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q079  |

### `data/app-interface/changetype/jira-board-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q067  |
|   20 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q068  |
|   22 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q066  |
|   26 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q173  |
|   27 | <code>changes[1].jsonPathSelectors[1]</code> | change-type selector / configuration | Q091  |
|   28 | <code>changes[1].jsonPathSelectors[2]</code> | change-type selector / configuration | Q155  |
|   29 | <code>changes[1].jsonPathSelectors[3]</code> | change-type selector / configuration | Q154  |
|   30 | <code>changes[1].jsonPathSelectors[4]</code> | change-type selector / configuration | Q153  |
|   31 | <code>changes[1].jsonPathSelectors[5]</code> | change-type selector / configuration | Q152  |

### `data/app-interface/changetype/managed-sso-client-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   25 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q208  |
|   27 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q204  |
|   31 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q208  |
|   33 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q204  |

### `data/app-interface/changetype/monitoring-role-access-allow-all.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q042  |

### `data/app-interface/changetype/namespace-labels.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q157  |

### `data/app-interface/changetype/namespace-limitranges.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q160  |

### `data/app-interface/changetype/namespace-networkpolicies.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q200  |

### `data/app-interface/changetype/namespace-openshift-resources-path.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q210  |
|   21 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q212  |
|   22 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q215  |
|   23 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q214  |

### `data/app-interface/changetype/namespace-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   34 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q174  |
|   37 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q133  |
|   38 | <code>changes[1].jsonPathSelectors[1]</code> | change-type selector / configuration | Q166  |
|   41 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q213  |
|   44 | <code>changes[3].jsonPathSelectors[0]</code> | change-type selector / configuration | Q209  |
|   50 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q150  |
|   56 | <code>changes[5].context.selector</code>     | ownership context / configuration    | Q060  |
|   62 | <code>changes[6].context.selector</code>     | ownership context / configuration    | Q060  |

### `data/app-interface/changetype/ocm-github-resource-template-editor.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q206  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q207  |

### `data/app-interface/changetype/ocm-org-owner.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q043  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q064  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q375  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q374  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q348  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q235  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q143  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q377  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q376  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q048  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q049  |

### `data/app-interface/changetype/osd-fleet-manager-alerting-sector-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q205  |

### `data/app-interface/changetype/otel-scrape-config-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q359  |

### `data/app-interface/changetype/parameter-group-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/query-validation-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   24 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q241  |
|   30 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q241  |
|   37 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q341  |
|   43 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q341  |

### `data/app-interface/changetype/rds-defaults-account-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q052  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q168  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q146  |

### `data/app-interface/changetype/rds-defaults-maintainer.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q088  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q063  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q163  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q100  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q053  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q227  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q097  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q366  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q151  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q146  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q171  |

### `data/app-interface/changetype/rds-kessel-debezium-tier1-review.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   22 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q118  |
|   23 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q119  |
|   24 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q121  |
|   25 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q116  |

### `data/app-interface/changetype/rds-kessel-debezium-tier2-review.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   24 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q117  |
|   25 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q120  |
|   26 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q114  |

### `data/app-interface/changetype/rds-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q113  |
|   24 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q116  |
|   30 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q116  |
|   37 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q121  |
|   43 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q121  |
|   50 | <code>changes[5].context.selector</code>     | ownership context / configuration    | Q115  |
|   56 | <code>changes[6].context.selector</code>     | ownership context / configuration    | Q115  |

### `data/app-interface/changetype/rds-proxy-defaults-maintainer.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q080  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q084  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q085  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q099  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q137  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q138  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q139  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q144  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q161  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q169  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q170  |
|   29 | <code>changes[0].jsonPathSelectors[11]</code> | change-type selector / configuration | Q246  |
|   30 | <code>changes[0].jsonPathSelectors[12]</code> | change-type selector / configuration | Q353  |

### `data/app-interface/changetype/rds-proxy-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q122  |
|   24 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q123  |
|   30 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q123  |

### `data/app-interface/changetype/resource-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/restrictive-cluster-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q081  |
|   21 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q096  |
|   22 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q351  |

### `data/app-interface/changetype/restrictive-ocm-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q044  |

### `data/app-interface/changetype/restrictive-ocm-environment-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q379  |
|   21 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q044  |

### `data/app-interface/changetype/restrictive-vault-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q050  |

### `data/app-interface/changetype/role-manager.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q344  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q343  |
|   26 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q344  |
|   28 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q343  |
|   33 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q344  |
|   35 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q343  |
|   39 | <code>changes[3].jsonPathSelectors[0]</code> | change-type selector / configuration | Q134  |
|   40 | <code>changes[3].jsonPathSelectors[1]</code> | change-type selector / configuration | Q158  |

### `data/app-interface/changetype/s3-defaults-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   17 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q082  |
|   18 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q159  |
|   19 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q095  |

### `data/app-interface/changetype/s3-maintainer.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q124  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q126  |
|   26 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q125  |
|   32 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q125  |
|   39 | <code>changes[3].context.selector</code>     | ownership context / configuration    | Q127  |
|   45 | <code>changes[4].context.selector</code>     | ownership context / configuration    | Q127  |

### `data/app-interface/changetype/saas-file-namespace-target-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q280  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q266  |

### `data/app-interface/changetype/saas-file-progressive-delivery.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q277  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q276  |

### `data/app-interface/changetype/saas-file-self-service-validate-targets-in-app.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   20 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q356  |
|   21 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q090  |
|   22 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q225  |
|   23 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q346  |
|   24 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q380  |
|   25 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q164  |
|   26 | <code>changes[0].jsonPathSelectors[6]</code> | change-type selector / configuration | Q248  |

### `data/app-interface/changetype/saas-file-self-service.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q054  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q356  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q141  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q094  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q091  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q090  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q225  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q346  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q371  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q380  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q164  |
|   29 | <code>changes[0].jsonPathSelectors[11]</code> | change-type selector / configuration | Q250  |
|   30 | <code>changes[0].jsonPathSelectors[12]</code> | change-type selector / configuration | Q249  |
|   31 | <code>changes[0].jsonPathSelectors[13]</code> | change-type selector / configuration | Q251  |
|   32 | <code>changes[0].jsonPathSelectors[14]</code> | change-type selector / configuration | Q259  |
|   33 | <code>changes[0].jsonPathSelectors[15]</code> | change-type selector / configuration | Q260  |
|   34 | <code>changes[0].jsonPathSelectors[16]</code> | change-type selector / configuration | Q265  |
|   35 | <code>changes[0].jsonPathSelectors[17]</code> | change-type selector / configuration | Q277  |
|   36 | <code>changes[0].jsonPathSelectors[18]</code> | change-type selector / configuration | Q267  |
|   37 | <code>changes[0].jsonPathSelectors[19]</code> | change-type selector / configuration | Q278  |
|   38 | <code>changes[0].jsonPathSelectors[20]</code> | change-type selector / configuration | Q279  |
|   39 | <code>changes[0].jsonPathSelectors[21]</code> | change-type selector / configuration | Q264  |
|   40 | <code>changes[0].jsonPathSelectors[22]</code> | change-type selector / configuration | Q263  |
|   41 | <code>changes[0].jsonPathSelectors[23]</code> | change-type selector / configuration | Q262  |
|   42 | <code>changes[0].jsonPathSelectors[24]</code> | change-type selector / configuration | Q275  |

### `data/app-interface/changetype/saas-file-target-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q261  |

### `data/app-interface/changetype/saas-file-target-progressive-delivery.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q244  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q233  |

### `data/app-interface/changetype/saas-file-target-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q173  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q244  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q225  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q347  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q378  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q140  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code> | change-type selector / configuration | Q142  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code> | change-type selector / configuration | Q092  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code> | change-type selector / configuration | Q086  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code> | change-type selector / configuration | Q232  |

### `data/app-interface/changetype/scheduler-editor.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q345  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q091  |

### `data/app-interface/changetype/scorecard-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/secret-promoter.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q220  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q218  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q217  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q219  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q216  |

### `data/app-interface/changetype/self-service-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q349  |

### `data/app-interface/changetype/shared-resources-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/shared-resources-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q213  |

### `data/app-interface/changetype/shared-resources-secret-promoter.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q220  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q218  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q217  |

### `data/app-interface/changetype/slack-usergroup-editor.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q091  |
|   22 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q065  |
|   23 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q201  |

### `data/app-interface/changetype/sql-query-approver.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   19 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   21 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q174  |
|   26 | <code>changes[1].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |
|   28 | <code>changes[1].context.selector</code>     | ownership context / configuration    | Q174  |
|   33 | <code>changes[2].jsonPathSelectors[0]</code> | change-type selector / configuration | Q086  |
|   35 | <code>changes[2].context.selector</code>     | ownership context / configuration    | Q174  |

### `data/app-interface/changetype/tekton-provider-defaults-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/template-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/template-collection-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/template-test-admin.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/terraform-repo-owner.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q244  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q086  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q245  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q370  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q131  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q384  |
|   25 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q047  |

### `data/app-interface/changetype/terraform-repo-self-service.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q244  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code> | change-type selector / configuration | Q086  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code> | change-type selector / configuration | Q245  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code> | change-type selector / configuration | Q370  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code> | change-type selector / configuration | Q131  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code> | change-type selector / configuration | Q384  |

### `data/app-interface/changetype/unleash-feature-toggle.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q001  |

### `data/app-interface/changetype/unleash-instance-owner.yml`

| Line | Field                                    | Category / source                 | Query |
| ---: | ---------------------------------------- | --------------------------------- | ----- |
|   21 | <code>changes[0].context.selector</code> | ownership context / configuration | Q350  |

### `data/app-interface/changetype/unleash-project.yml`

| Line | Field                                    | Category / source                 | Query |
| ---: | ---------------------------------------- | --------------------------------- | ----- |
|   21 | <code>changes[0].context.selector</code> | ownership context / configuration | Q373  |
|   27 | <code>changes[1].context.selector</code> | ownership context / configuration | Q373  |

### `data/app-interface/changetype/user-policy-role-linker.yml`

| Line | Field                                        | Category / source                    | Query |
| ---: | -------------------------------------------- | ------------------------------------ | ----- |
|   21 | <code>changes[0].jsonPathSelectors[0]</code> | change-type selector / configuration | Q382  |
|   23 | <code>changes[0].context.selector</code>     | ownership context / configuration    | Q381  |

### `data/app-interface/changetype/user-self-service.yml`

| Line | Field                                              | Category / source                    | Query |
| ---: | -------------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / configuration | Q173  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / configuration | Q221  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>       | change-type selector / configuration | Q132  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>       | change-type selector / configuration | Q240  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>       | change-type selector / configuration | Q223  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>       | change-type selector / configuration | Q062  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>       | change-type selector / configuration | Q234  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>       | change-type selector / configuration | Q369  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>       | change-type selector / configuration | Q368  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>       | change-type selector / configuration | Q157  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code>      | change-type selector / configuration | Q071  |
|   32 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / configuration   | Q014  |

### `data/app-interface/changetype/vector-pipeline-config-maintainer.yml`

| Line | Field                                         | Category / source                    | Query |
| ---: | --------------------------------------------- | ------------------------------------ | ----- |
|   18 | <code>changes[0].jsonPathSelectors[0]</code>  | change-type selector / configuration | Q258  |
|   19 | <code>changes[0].jsonPathSelectors[1]</code>  | change-type selector / configuration | Q255  |
|   20 | <code>changes[0].jsonPathSelectors[2]</code>  | change-type selector / configuration | Q257  |
|   21 | <code>changes[0].jsonPathSelectors[3]</code>  | change-type selector / configuration | Q253  |
|   22 | <code>changes[0].jsonPathSelectors[4]</code>  | change-type selector / configuration | Q252  |
|   23 | <code>changes[0].jsonPathSelectors[5]</code>  | change-type selector / configuration | Q254  |
|   24 | <code>changes[0].jsonPathSelectors[6]</code>  | change-type selector / configuration | Q274  |
|   25 | <code>changes[0].jsonPathSelectors[7]</code>  | change-type selector / configuration | Q271  |
|   26 | <code>changes[0].jsonPathSelectors[8]</code>  | change-type selector / configuration | Q273  |
|   27 | <code>changes[0].jsonPathSelectors[9]</code>  | change-type selector / configuration | Q269  |
|   28 | <code>changes[0].jsonPathSelectors[10]</code> | change-type selector / configuration | Q268  |
|   29 | <code>changes[0].jsonPathSelectors[11]</code> | change-type selector / configuration | Q270  |

### `data/dependencies/status-board/production.yml`

| Line | Field                                      | Category / source                     | Query |
| ---: | ------------------------------------------ | ------------------------------------- | ----- |
|   15 | <code>globalAppSelectors.exclude[0]</code> | status-board selector / configuration | Q057  |

### `data/dependencies/status-board/stage.yml`

| Line | Field                                      | Category / source                     | Query |
| ---: | ------------------------------------------ | ------------------------------------- | ----- |
|   15 | <code>globalAppSelectors.exclude[0]</code> | status-board selector / configuration | Q057  |

### `data/services/advanced-cluster-security/cicd/saas-app-sre-acs-per-cluster.yml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   47 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q195  |
|   56 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q196  |

### `data/services/app-sre/cicd/ci-int/saas-openshift-cert-manager-routes.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   55 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q198  |
|   61 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q197  |

### `data/services/app-sre/selectorsyncset-sector-demo/deploy.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q194  |
|   66 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q194  |
|   78 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q194  |
|   90 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q194  |

### `data/services/app-sre/selectorsyncset-sector-demo/test-sector-b.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   30 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q193  |

### `data/services/ocm/osd-fleet-manager/cicd/hypershift-cloudwatch-logging.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   62 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q184  |
|   71 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q184  |
|   80 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q184  |
|   89 | <code>resourceTemplates[1].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q184  |
|  104 | <code>resourceTemplates[2].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  113 | <code>resourceTemplates[2].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  122 | <code>resourceTemplates[2].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  131 | <code>resourceTemplates[2].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  140 | <code>resourceTemplates[2].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  149 | <code>resourceTemplates[2].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  158 | <code>resourceTemplates[2].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  167 | <code>resourceTemplates[2].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  176 | <code>resourceTemplates[2].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  185 | <code>resourceTemplates[2].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  194 | <code>resourceTemplates[2].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  203 | <code>resourceTemplates[2].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  212 | <code>resourceTemplates[2].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  221 | <code>resourceTemplates[2].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  230 | <code>resourceTemplates[2].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  239 | <code>resourceTemplates[2].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  248 | <code>resourceTemplates[2].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  257 | <code>resourceTemplates[2].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  266 | <code>resourceTemplates[2].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  275 | <code>resourceTemplates[2].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  284 | <code>resourceTemplates[2].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  293 | <code>resourceTemplates[2].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  302 | <code>resourceTemplates[2].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  311 | <code>resourceTemplates[2].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  320 | <code>resourceTemplates[2].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  329 | <code>resourceTemplates[2].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  338 | <code>resourceTemplates[2].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  347 | <code>resourceTemplates[2].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  356 | <code>resourceTemplates[2].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  365 | <code>resourceTemplates[2].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/osd-operators/cicd/saas/network-observability-operator/deploy.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   36 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |

### `data/services/osd-operators/cicd/saas/saas-dynatrace-activegate.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   69 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q175  |
|   94 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q178  |
|  119 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q178  |
|  146 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  171 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  196 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  221 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  246 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  271 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  296 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q176  |
|  324 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q175  |
|  332 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q178  |
|  340 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q177  |

### `data/services/osd-operators/cicd/saas/saas-dynatrace/dynatrace-bootstrap-job.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   39 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|   54 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   73 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|   87 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  104 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |

### `data/services/osd-operators/cicd/saas/saas-dynatrace/dynatrace-dynakube.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   39 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|   57 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|   81 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  101 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|  123 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|  165 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|  185 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |

### `data/services/osd-operators/cicd/saas/saas-dynatrace/dynatrace-opentelemetry-collector-service-cluster.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   39 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|   53 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   70 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   84 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|   97 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  115 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |

### `data/services/osd-operators/cicd/saas/saas-dynatrace/dynatrace-opentelemetry-collector.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   39 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|   53 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   71 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   92 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  105 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  123 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |

### `data/services/osd-operators/cicd/saas/saas-rmo-config-integration.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   57 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   71 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   85 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |

### `data/services/osd-operators/cicd/saas/saas-rmo-config-production.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   57 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   71 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   85 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   99 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  113 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  127 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  141 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  156 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  171 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
|  186 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  201 | <code>resourceTemplates[0].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
|  215 | <code>resourceTemplates[0].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
|  232 | <code>resourceTemplates[0].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
|  248 | <code>resourceTemplates[0].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  262 | <code>resourceTemplates[0].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  276 | <code>resourceTemplates[0].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  290 | <code>resourceTemplates[0].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  304 | <code>resourceTemplates[0].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  318 | <code>resourceTemplates[0].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  332 | <code>resourceTemplates[0].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  346 | <code>resourceTemplates[0].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  360 | <code>resourceTemplates[0].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  374 | <code>resourceTemplates[0].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  388 | <code>resourceTemplates[0].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  402 | <code>resourceTemplates[0].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  416 | <code>resourceTemplates[0].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  430 | <code>resourceTemplates[0].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  444 | <code>resourceTemplates[0].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
|  460 | <code>resourceTemplates[0].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  473 | <code>resourceTemplates[0].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  487 | <code>resourceTemplates[0].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  501 | <code>resourceTemplates[0].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  515 | <code>resourceTemplates[0].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  529 | <code>resourceTemplates[0].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  543 | <code>resourceTemplates[0].targets[34].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/osd-operators/cicd/saas/saas-rmo-config-stage.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   57 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   71 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   85 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   99 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  113 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  127 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  141 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  155 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  169 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |

### `data/services/osd-operators/package-operator/cicd/saas/saas-package-operator.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   47 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|   60 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|   69 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|   85 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|   98 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|  107 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |
|  123 | <code>resourceTemplates[2].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q179  |
|  136 | <code>resourceTemplates[2].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q181  |
|  145 | <code>resourceTemplates[2].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q180  |

### `data/services/rhobs/rhobs/cicd/saas-log-event-collector-integration.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   70 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   86 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |

### `data/services/rhobs/rhobs/cicd/saas-log-event-collector-production.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   71 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   88 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  105 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  126 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  147 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  168 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  191 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  214 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
|  237 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  260 | <code>resourceTemplates[0].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
|  281 | <code>resourceTemplates[0].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
|  308 | <code>resourceTemplates[0].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
|  333 | <code>resourceTemplates[0].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  354 | <code>resourceTemplates[0].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  375 | <code>resourceTemplates[0].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  396 | <code>resourceTemplates[0].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  417 | <code>resourceTemplates[0].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  438 | <code>resourceTemplates[0].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  459 | <code>resourceTemplates[0].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  480 | <code>resourceTemplates[0].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  501 | <code>resourceTemplates[0].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  522 | <code>resourceTemplates[0].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  543 | <code>resourceTemplates[0].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  564 | <code>resourceTemplates[0].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  585 | <code>resourceTemplates[0].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  606 | <code>resourceTemplates[0].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
|  631 | <code>resourceTemplates[0].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  652 | <code>resourceTemplates[0].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  673 | <code>resourceTemplates[0].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  694 | <code>resourceTemplates[0].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  715 | <code>resourceTemplates[0].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  736 | <code>resourceTemplates[0].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  757 | <code>resourceTemplates[0].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  782 | <code>resourceTemplates[0].targets[34].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/rhobs/rhobs/cicd/saas-log-event-collector-stage.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   70 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   86 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  102 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  118 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  134 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  150 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  166 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  182 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |

### `data/services/rhobs/rhobs/cicd/saas-log-forwarder-integration.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   70 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   86 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |

### `data/services/rhobs/rhobs/cicd/saas-log-forwarder-production.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   71 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   88 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  105 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  126 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  147 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  168 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  191 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  214 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
|  237 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  260 | <code>resourceTemplates[0].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
|  281 | <code>resourceTemplates[0].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
|  308 | <code>resourceTemplates[0].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
|  333 | <code>resourceTemplates[0].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  354 | <code>resourceTemplates[0].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  375 | <code>resourceTemplates[0].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  396 | <code>resourceTemplates[0].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  417 | <code>resourceTemplates[0].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  438 | <code>resourceTemplates[0].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  459 | <code>resourceTemplates[0].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  480 | <code>resourceTemplates[0].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  501 | <code>resourceTemplates[0].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  522 | <code>resourceTemplates[0].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  543 | <code>resourceTemplates[0].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  564 | <code>resourceTemplates[0].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  585 | <code>resourceTemplates[0].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  606 | <code>resourceTemplates[0].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
|  631 | <code>resourceTemplates[0].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  652 | <code>resourceTemplates[0].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  673 | <code>resourceTemplates[0].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  694 | <code>resourceTemplates[0].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  715 | <code>resourceTemplates[0].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  736 | <code>resourceTemplates[0].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  757 | <code>resourceTemplates[0].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  782 | <code>resourceTemplates[0].targets[34].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/rhobs/rhobs/cicd/saas-log-forwarder-stage.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   54 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   70 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   86 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  102 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  118 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  134 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  150 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  166 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  182 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |

### `data/services/rhobs/rhobs/cicd/saas-log-token-refresher-integration.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   65 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   81 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   97 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |

### `data/services/rhobs/rhobs/cicd/saas-log-token-refresher-production.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   65 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   83 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  101 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  119 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  141 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  163 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  185 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  209 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  233 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
|  257 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  281 | <code>resourceTemplates[0].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
|  303 | <code>resourceTemplates[0].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
|  331 | <code>resourceTemplates[0].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
|  357 | <code>resourceTemplates[0].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  379 | <code>resourceTemplates[0].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  401 | <code>resourceTemplates[0].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  423 | <code>resourceTemplates[0].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  445 | <code>resourceTemplates[0].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  467 | <code>resourceTemplates[0].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  489 | <code>resourceTemplates[0].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  511 | <code>resourceTemplates[0].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  533 | <code>resourceTemplates[0].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  555 | <code>resourceTemplates[0].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  577 | <code>resourceTemplates[0].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  599 | <code>resourceTemplates[0].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  621 | <code>resourceTemplates[0].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  643 | <code>resourceTemplates[0].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
|  669 | <code>resourceTemplates[0].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  691 | <code>resourceTemplates[0].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  713 | <code>resourceTemplates[0].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  735 | <code>resourceTemplates[0].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  757 | <code>resourceTemplates[0].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  779 | <code>resourceTemplates[0].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  800 | <code>resourceTemplates[0].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  826 | <code>resourceTemplates[0].targets[34].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/rhobs/rhobs/cicd/saas-log-token-refresher-stage.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   65 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   81 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   97 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  113 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  129 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  145 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  161 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  177 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  194 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |

### `data/services/rhobs/rhobs/cicd/saas-metric-collection-integration.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   68 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|   85 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|  102 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |
|  124 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q182  |

### `data/services/rhobs/rhobs/cicd/saas-metric-collection-production.yaml`

| Line | Field                                                                                        | Category / source                  | Query |
| ---: | -------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   67 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|   86 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  105 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  124 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  147 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  170 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  193 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  218 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  243 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
|  268 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  293 | <code>resourceTemplates[0].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
|  316 | <code>resourceTemplates[0].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
|  345 | <code>resourceTemplates[0].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
|  372 | <code>resourceTemplates[0].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  395 | <code>resourceTemplates[0].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  418 | <code>resourceTemplates[0].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  441 | <code>resourceTemplates[0].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  464 | <code>resourceTemplates[0].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  487 | <code>resourceTemplates[0].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  510 | <code>resourceTemplates[0].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  533 | <code>resourceTemplates[0].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  556 | <code>resourceTemplates[0].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  579 | <code>resourceTemplates[0].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  602 | <code>resourceTemplates[0].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  625 | <code>resourceTemplates[0].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  648 | <code>resourceTemplates[0].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  671 | <code>resourceTemplates[0].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
|  698 | <code>resourceTemplates[0].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  721 | <code>resourceTemplates[0].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  744 | <code>resourceTemplates[0].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  767 | <code>resourceTemplates[0].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  790 | <code>resourceTemplates[0].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  813 | <code>resourceTemplates[0].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  835 | <code>resourceTemplates[0].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  862 | <code>resourceTemplates[0].targets[34].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
|  889 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  902 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  915 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q183  |
|  928 | <code>resourceTemplates[1].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q186  |
|  941 | <code>resourceTemplates[1].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q187  |
|  954 | <code>resourceTemplates[1].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
|  969 | <code>resourceTemplates[1].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q190  |
|  982 | <code>resourceTemplates[1].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q191  |
|  997 | <code>resourceTemplates[1].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q188  |
| 1012 | <code>resourceTemplates[1].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code>  | namespace selector / configuration | Q189  |
| 1027 | <code>resourceTemplates[1].targets[10].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q187  |
| 1040 | <code>resourceTemplates[1].targets[11].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q191  |
| 1059 | <code>resourceTemplates[1].targets[12].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q190  |
| 1076 | <code>resourceTemplates[1].targets[13].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1089 | <code>resourceTemplates[1].targets[14].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1102 | <code>resourceTemplates[1].targets[15].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1115 | <code>resourceTemplates[1].targets[16].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1128 | <code>resourceTemplates[1].targets[17].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1141 | <code>resourceTemplates[1].targets[18].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1154 | <code>resourceTemplates[1].targets[19].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1167 | <code>resourceTemplates[1].targets[20].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1180 | <code>resourceTemplates[1].targets[21].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1193 | <code>resourceTemplates[1].targets[22].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1206 | <code>resourceTemplates[1].targets[23].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1219 | <code>resourceTemplates[1].targets[24].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1232 | <code>resourceTemplates[1].targets[25].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1245 | <code>resourceTemplates[1].targets[26].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q186  |
| 1262 | <code>resourceTemplates[1].targets[27].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1275 | <code>resourceTemplates[1].targets[28].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1288 | <code>resourceTemplates[1].targets[29].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1301 | <code>resourceTemplates[1].targets[30].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1314 | <code>resourceTemplates[1].targets[31].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1327 | <code>resourceTemplates[1].targets[32].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |
| 1340 | <code>resourceTemplates[1].targets[33].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q183  |

### `data/services/rhobs/rhobs/cicd/saas-metric-collection-stage.yaml`

| Line | Field                                                                                       | Category / source                  | Query |
| ---: | ------------------------------------------------------------------------------------------- | ---------------------------------- | ----- |
|   68 | <code>resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|   86 | <code>resourceTemplates[0].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  104 | <code>resourceTemplates[0].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  122 | <code>resourceTemplates[0].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  140 | <code>resourceTemplates[0].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  158 | <code>resourceTemplates[0].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  176 | <code>resourceTemplates[0].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  194 | <code>resourceTemplates[0].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  212 | <code>resourceTemplates[0].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  231 | <code>resourceTemplates[0].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  253 | <code>resourceTemplates[1].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  266 | <code>resourceTemplates[1].targets[1].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  279 | <code>resourceTemplates[1].targets[2].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  292 | <code>resourceTemplates[1].targets[3].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  305 | <code>resourceTemplates[1].targets[4].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  318 | <code>resourceTemplates[1].targets[5].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  331 | <code>resourceTemplates[1].targets[6].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  344 | <code>resourceTemplates[1].targets[7].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  357 | <code>resourceTemplates[1].targets[8].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |
|  370 | <code>resourceTemplates[1].targets[9].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / configuration | Q184  |

### `data/templating/templates/aws-account/app-sre-admin-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   14 | <code>patch.path</code> | template patch path / configuration | Q004  |

### `data/templating/templates/aws-account/aws-resource-exporter/configmap.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   19 | <code>patch.path</code>       | template patch path / configuration       | Q009  |
|   20 | <code>patch.identifier</code> | template patch identifier / configuration | Q040  |

### `data/templating/templates/aws-account/aws-resource-exporter/prometheus-rules.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   24 | <code>patch.path</code>       | template patch path / configuration       | Q010  |
|   25 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/aws-account/aws-resource-exporter/saas.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   29 | <code>patch.path</code> | template patch path / configuration | Q022  |

### `data/templating/templates/aws-account/aws-resource-exporter/service-account.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   22 | <code>patch.path</code> | template patch path / configuration | Q006  |

### `data/templating/templates/aws-account/aws-resource-exporter/service-monitor.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   28 | <code>patch.path</code>       | template patch path / configuration       | Q009  |
|   29 | <code>patch.identifier</code> | template patch identifier / configuration | Q040  |

### `data/templating/templates/aws-account/cloudwatch-exporter-log-delivery/configmap.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   16 | <code>patch.path</code>       | template patch path / configuration       | Q009  |
|   17 | <code>patch.identifier</code> | template patch identifier / configuration | Q041  |

### `data/templating/templates/aws-account/cloudwatch-exporter-log-delivery/saas.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   15 | <code>patch.path</code> | template patch path / configuration | Q023  |

### `data/templating/templates/aws-account/cloudwatch-exporter-log-delivery/service-monitor.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   16 | <code>patch.path</code>       | template patch path / configuration       | Q009  |
|   17 | <code>patch.identifier</code> | template patch identifier / configuration | Q040  |

### `data/templating/templates/aws-account/cloudwatch-exporter/prometheus-rules-account.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   22 | <code>patch.path</code>       | template patch path / configuration       | Q011  |
|   23 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/aws-account/cloudwatch-exporter/prometheus-rules.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   24 | <code>patch.path</code>       | template patch path / configuration       | Q012  |
|   25 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/aws-account/cloudwatch-exporter/saas.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   29 | <code>patch.path</code> | template patch path / configuration | Q023  |

### `data/templating/templates/aws-account/cloudwatch-exporter/service-account.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   22 | <code>patch.path</code> | template patch path / configuration | Q007  |

### `data/templating/templates/aws-account/cloudwatch-exporter/service-monitor.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   28 | <code>patch.path</code>       | template patch path / configuration       | Q009  |
|   29 | <code>patch.identifier</code> | template patch identifier / configuration | Q040  |

### `data/templating/templates/aws-account/patch-rosa-automation-roles.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   14 | <code>patch.path</code> | template patch path / configuration | Q006  |

### `data/templating/templates/cluster-creation/appsrep09ue1-peering-accepter.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   14 | <code>patch.path</code> | template patch path / configuration | Q015  |

### `data/templating/templates/cluster-creation/appsres09ue1-peering-accepter.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   14 | <code>patch.path</code> | template patch path / configuration | Q015  |

### `data/templating/templates/cluster-creation/patch-app-sre-gitlab-bot-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q036  |

### `data/templating/templates/cluster-creation/patch-app-sre-role.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   11 | <code>patch.path</code>       | template patch path / configuration       | Q002  |
|   12 | <code>patch.identifier</code> | template patch identifier / configuration | Q005  |

### `data/templating/templates/cluster-dressup/cert-manager/cert-manager-observability.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/clowder/monitoring-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/clowder/namespace-access.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/clowder/saas-clowdenvironment.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q025  |

### `data/templating/templates/cluster-dressup/clowder/saas-clowder-plugin.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q026  |

### `data/templating/templates/cluster-dressup/clowder/saas-clowder.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q024  |

### `data/templating/templates/cluster-dressup/clowder/service-monitor.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   15 | <code>patch.path</code> | template patch path / configuration | Q009  |

### `data/templating/templates/cluster-dressup/cost-management/saas-costmanagement.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q027  |

### `data/templating/templates/cluster-dressup/dvo-namespace-access.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/netobserv/saas-netobserv.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q030  |

### `data/templating/templates/cluster-dressup/observability/app-sre-osdv4-monitored-clusters-view.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/observability/cluster-updates.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   13 | <code>patch.path</code> | template patch path / configuration | Q001  |

### `data/templating/templates/cluster-dressup/observability/deadmanssnitch-prometheusrule.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q009  |

### `data/templating/templates/cluster-dressup/observability/devshift.net-alertmanager.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q016  |

### `data/templating/templates/cluster-dressup/observability/devshift.net-prometheus.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q016  |

### `data/templating/templates/cluster-dressup/observability/devshift.net-thanos-querier-grpc.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q016  |

### `data/templating/templates/cluster-dressup/observability/devshift.net-thanos-querier.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q016  |

### `data/templating/templates/cluster-dressup/observability/gateway-api-monitoring-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   13 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/cluster-dressup/observability/openshift-customer-monitoring-gateway-podmonitor.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q009  |

### `data/templating/templates/cluster-dressup/observability/saas-coo-monitoring-stack.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q029  |

### `data/templating/templates/cluster-dressup/observability/saas-coo-thanos-querier.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q034  |

### `data/templating/templates/cluster-dressup/observability/saas-nginx-proxy.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q031  |

### `data/templating/templates/cluster-dressup/saas-event-router.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q028  |

### `data/templating/templates/hcp-collection/saas-logs-event-collector-target.yml`

| Line | Field                                                                                      | Category / source                                         | Query |
| ---: | ------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ----- |
|   12 | <code>patch.path</code>                                                                    | template patch path / configuration                       | Q019  |
|   25 | <code>template.&lt;embedded YAML&gt;.namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / template generator (text extraction) | Q192  |

### `data/templating/templates/hcp-collection/saas-logs-forwarder-target.yml`

| Line | Field                                                                                      | Category / source                                         | Query |
| ---: | ------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ----- |
|   12 | <code>patch.path</code>                                                                    | template patch path / configuration                       | Q020  |
|   25 | <code>template.&lt;embedded YAML&gt;.namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / template generator (text extraction) | Q192  |

### `data/templating/templates/hcp-collection/saas-logs-token-refresher-target.yml`

| Line | Field                                                                                      | Category / source                                         | Query |
| ---: | ------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ----- |
|   12 | <code>patch.path</code>                                                                    | template patch path / configuration                       | Q021  |
|   25 | <code>template.&lt;embedded YAML&gt;.namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / template generator (text extraction) | Q192  |

### `data/templating/templates/hcp-collection/saas-metrics-target.yml`

| Line | Field                                                                                      | Category / source                                         | Query |
| ---: | ------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ----- |
|   12 | <code>patch.path</code>                                                                    | template patch path / configuration                       | Q018  |
|   25 | <code>template.&lt;embedded YAML&gt;.namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / template generator (text extraction) | Q192  |

### `data/templating/templates/hcp-collection/saas-rmo-config-target.yml`

| Line | Field                                                                                      | Category / source                                         | Query |
| ---: | ------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ----- |
|   12 | <code>patch.path</code>                                                                    | template patch path / configuration                       | Q018  |
|   25 | <code>template.&lt;embedded YAML&gt;.namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / template generator (text extraction) | Q192  |

### `data/templating/templates/rhobs-cell/access-dev-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/rhobs-cell/access-observatorium-bot-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/rhobs-cell/monitoring-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/rhobs-cell/saas-alertmanager.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-gateway-bundle.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-gateway-tenant-secret.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-hcp-rules.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-loki.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-objstore-default-logs-s3.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   12 | <code>patch.path</code>       | template patch path / configuration       | Q003  |
|   13 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/rhobs-cell/saas-objstore-default-metrics-s3.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   12 | <code>patch.path</code>       | template patch path / configuration       | Q003  |
|   13 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/rhobs-cell/saas-objstore-loki-deploy.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q032  |

### `data/templating/templates/rhobs-cell/saas-objstore-thanos-deploy.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q033  |

### `data/templating/templates/rhobs-cell/saas-operator-thanos.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-synthetics-agent.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/rhobs-cell/saas-synthetics-api.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   12 | <code>patch.path</code> | template patch path / configuration | Q017  |

### `data/templating/templates/service-bootstrap/monitoring-role.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q002  |

### `data/templating/templates/service-bootstrap/slack-workspace.yml`

| Line | Field                         | Category / source                         | Query |
| ---: | ----------------------------- | ----------------------------------------- | ----- |
|   11 | <code>patch.path</code>       | template patch path / configuration       | Q008  |
|   12 | <code>patch.identifier</code> | template patch identifier / configuration | Q001  |

### `data/templating/templates/service-bootstrap/user.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   11 | <code>patch.path</code> | template patch path / configuration | Q035  |

### `data/templating/templates/terraform-init/account.yml`

| Line | Field                   | Category / source                   | Query |
| ---: | ----------------------- | ----------------------------------- | ----- |
|   15 | <code>patch.path</code> | template patch path / configuration | Q001  |

### `data/templating/tests/hcp-collection/saas-logs-event-collector-target-production.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   36 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q183  |

### `data/templating/tests/hcp-collection/saas-logs-event-collector-target.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   35 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q182  |

### `data/templating/tests/hcp-collection/saas-logs-forwarder-target-production.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   36 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q183  |

### `data/templating/tests/hcp-collection/saas-logs-forwarder-target.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   35 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q182  |

### `data/templating/tests/hcp-collection/saas-logs-token-refresher-target-production.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   37 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q183  |

### `data/templating/tests/hcp-collection/saas-logs-token-refresher-target.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   36 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q182  |

### `data/templating/tests/hcp-collection/saas-metrics-target-production.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   37 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q183  |

### `data/templating/tests/hcp-collection/saas-metrics-target.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   36 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q182  |

### `data/templating/tests/hcp-collection/saas-rmo-config-target-hive-shard.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   36 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q185  |

### `data/templating/tests/hcp-collection/saas-rmo-config-target.yml`

| Line | Field                                                                                                                            | Category / source                              | Query |
| ---: | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- |
|   35 | <code>expectedOutput.&lt;embedded YAML&gt;.resourceTemplates[0].targets[0].namespaceSelector.jsonPathSelectors.include[0]</code> | namespace selector / expected generated output | Q182  |

### `docs/platform-users/repo-mechanics/change-types.md`

| Line | Field                                              | Category / source                            | Query |
| ---: | -------------------------------------------------- | -------------------------------------------- | ----- |
|   34 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q090  |
|  101 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q001  |
|  103 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q073  |
|  143 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q073  |
|  158 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q357  |
|  177 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q234  |
|  178 | <code>changes[0].jsonPathSelectors[1]</code>       | change-type selector / documentation example | Q132  |
|  182 | <code>implicitOwnership[0].jsonPathSelector</code> | implicit ownership / documentation example   | Q014  |
|  215 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q116  |
|  240 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q342  |
|  242 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q343  |
|  252 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q344  |
|  285 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q344  |
|  287 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q343  |
|  330 | <code>changes[0].jsonPathSelectors[0]</code>       | change-type selector / documentation example | Q382  |
|  332 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q381  |
|  346 | <code>changes[0].context.selector</code>           | ownership context / documentation example    | Q047  |
|  351 | <code>changes[1].context.selector</code>           | ownership context / documentation example    | Q047  |

## Dynamic Jinja calls and textual-reference audit

Jinja filter calls are actionable. Other references explain generators, validation assumptions, documentation, or unrelated Kubernetes CLI syntax; inspect their context before changing them.

### Jinja filter call

| File and line                                                         | Source text                                                                                                                                                                                                                                           |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <code>data/templating/templates/gabi/gabi-cluster-scope.yml:11</code> | <code>{{ "openshift-config" in (dynamic.cluster.clusters[0].namespaces &#124;map(attribute="name" )) and dynamic.gabi_instance &#124; matches_jsonpath('$.gabi_instances[*].instances[?namespace.cluster.name=="'+static.cluster_name+'"]') }}</code> |

### Kubernetes CLI dialect; not migrated

| File and line                                                                                                                                                     | Source text                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <code>data/aws/rhobsi01uw2/vpcs/vpc-request.yml:40</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01apne1/vpcs/vpc-request.yml:39</code>                                                                                                       | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01apse2/vpcs/vpc-request.yml:39</code>                                                                                                       | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01euc1/vpcs/vpc-request.yml:39</code>                                                                                                        | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01euw1/vpcs/vpc-request.yaml:40</code>                                                                                                       | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01sae1/vpcs/vpc-request.yaml:37</code>                                                                                                       | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01ue1/vpc/vpc-request.yml:41</code>                                                                                                          | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01ue2/vpcs/vpc-request.yml:39</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp01uw2/vpcs/vpc-request.yml:39</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp02ue1/vpcs/vpc-request.yml:39</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobsp03ue1/vpcs/vpc-request.yml:40</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobss01ue1/vpcs/vpc-request.yml:40</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/aws/rhobss01uw2/vpcs/vpc-request.yml:40</code>                                                                                                         | <code># oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>data/services/clowder/sop/clowdenv_sop.md:220</code>                                                                                                        | <code>oc get clowdenvironment env-myenv -o jsonpath='{.status.deployments.managedDeployments}'</code>                                                                                                                                                                                                                                                                                                                                  |
| <code>data/services/clowder/sop/clowdenv_sop.md:244</code>                                                                                                        | <code>oc get clowdenvironment env-myenv -o jsonpath='{.status}'</code>                                                                                                                                                                                                                                                                                                                                                                 |
| <code>data/services/clowder/sop/clowdenv_sop.md:387</code>                                                                                                        | <code>oc get clowdenvironment env-myenv -o jsonpath='{.spec.providers}'</code>                                                                                                                                                                                                                                                                                                                                                         |
| <code>data/services/clowder/sop/clowdenv_sop.md:412</code>                                                                                                        | <code>oc get clowdapp &lt;app-name&gt; -o jsonpath='{.spec.envName}'</code>                                                                                                                                                                                                                                                                                                                                                            |
| <code>docs/app-sre/olm-dance.sh:62</code>                                                                                                                         | <code>SUBSCRIPTION=$(oc get sub -n "${NAMESPACE}" -o jsonpath='{.items[].metadata.name}' &#124; grep "${SUBSCRIPTION}")</code>                                                                                                                                                                                                                                                                                                         |
| <code>docs/app-sre/olm-dance.sh:63</code>                                                                                                                         | <code>CATALOG_SOURCE=$(oc get catalogsource -n "${NAMESPACE}" -o jsonpath='{.items[].metadata.name}' &#124; grep "${SUBSCRIPTION}")</code>                                                                                                                                                                                                                                                                                             |
| <code>docs/app-sre/olm-dance.sh:64</code>                                                                                                                         | <code>OPERATOR_GROUP=$(oc get og -n "${NAMESPACE}" -o jsonpath='{.items[].metadata.name}' &#124; grep "${SUBSCRIPTION}")</code>                                                                                                                                                                                                                                                                                                        |
| <code>docs/app-sre/olm-dance.sh:80</code>                                                                                                                         | <code>for csv in $(oc get csv -n "${NAMESPACE}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' &#124; grep "${SUBSCRIPTION}")</code>                                                                                                                                                                                                                                                                                       |
| <code>docs/app-sre/platform-services/external-secrets-operator/architecture/architecture.md:104</code>                                                            | <code>oc get secretstores -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: {.status.conditions[0].reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                                                                   |
| <code>docs/app-sre/platform-services/glitchtip/sops/glitchtip-rds.md:40</code>                                                                                    | <code>oc rsh $(oc get pods -l app=debug-container -o jsonpath='{.items[0].metadata.name}') bash</code>                                                                                                                                                                                                                                                                                                                                 |
| <code>docs/app-sre/platform-services/skupper-network-monitoring/sop/CertificateError.md:24</code>                                                                 | <code>oc get secret &lt;secret-name&gt; -n &lt;namespace&gt; -o jsonpath='{.data.tls\.crt}' &#124; base64 --decode &#124; openssl x509 -text -noout</code>                                                                                                                                                                                                                                                                             |
| <code>docs/app-sre/platform-services/vault/on-prem/vault-internal-tls-certificates.md:204</code>                                                                  | <code>oc get secret vault-tls -n vault-production -o jsonpath='{.data.ca\.crt}' &#124; base64 -d &gt; /tmp/secret-ca.crt</code>                                                                                                                                                                                                                                                                                                        |
| <code>docs/app-sre/platform-services/vault/on-prem/vault-internal-tls-certificates.md:207</code>                                                                  | <code>oc get route vault-production -n vault-production -o jsonpath='{.spec.tls.destinationCACertificate}' &gt; /tmp/route-ca.crt</code>                                                                                                                                                                                                                                                                                               |
| <code>docs/app-sre/platform-services/vault/on-prem/vault-internal-tls-certificates.md:436</code>                                                                  | <code>oc get secret vault-tls -n vault-production -o jsonpath='{.data.tls\.crt}' &#124; base64 -d &#124; openssl x509 -text -noout</code>                                                                                                                                                                                                                                                                                              |
| <code>docs/app-sre/redhat-it-root-ca.md:53</code>                                                                                                                 | <code>oc get secret &lt;secret-name&gt; -n &lt;namespace&gt; -o jsonpath='{.data.ca\.crt}' \</code>                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/app-sre/runbook/app-interface-cluster/app-interface-onboard-cluster.md:121</code>                                                                      | <code>$ oc get secret -n dedicated-admin app-sre-bot -o jsonpath={.data.token} &#124; base64 --decode &amp;&amp; echo</code>                                                                                                                                                                                                                                                                                                           |
| <code>docs/app-sre/runbook/app-interface-cluster/app-interface-onboard-cluster.md:193</code>                                                                      | <code>$ oc get secret -n app-sre app-sre-cluster-admin-bot -o jsonpath={.data.token} &#124; base64 --decode &amp;&amp; echo</code>                                                                                                                                                                                                                                                                                                     |
| <code>docs/app-sre/runbook/openshift-ingress-routers.md:35</code>                                                                                                 | <code>&#96;&#96;&#96;oc get pods -n openshift-ingress -o=jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}'&#96;&#96;&#96;</code>                                                                                                                                                                                                                                                                                                 |
| <code>docs/app-sre/sops/alerts/prometheus/prometheus-PrometheusTSDBWALSizeHigh.md:72</code>                                                                       | <code>oc get pvc -n $NS -l app.kubernetes.io/name=prometheus -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.storageClassName}{"\n"}{end}'</code>                                                                                                                                                                                                                                                                           |
| <code>docs/app-sre/sops/general/app-interface-integrations-flow-and-failure-scenarios.md:34</code>                                                                | <code>1. Validate the &#96;time&#96; field matches the start time of the failures: &#96;oc get cm kube-root-ca.crt -o jsonpath="{['metadata']['managedFields']}" -n kube-system &#124; jq&#96;</code>                                                                                                                                                                                                                                  |
| <code>docs/app-sre/sops/general/ovn-migration.md:137</code>                                                                                                       | <code>oc get network.config.openshift.io cluster -o jsonpath='{.status.networkType}'</code>                                                                                                                                                                                                                                                                                                                                            |
| <code>docs/app-sre/sops/general/ovn-migration.md:143</code>                                                                                                       | <code>oc get network.config cluster -o=jsonpath='{.status.conditions}' &#124; jq .</code>                                                                                                                                                                                                                                                                                                                                              |
| <code>docs/app-sre/sops/general/vault-audit-device-failure.md:128</code>                                                                                          | <code>oc get storageclass -o jsonpath='{.items[*].allowVolumeExpansion}'</code>                                                                                                                                                                                                                                                                                                                                                        |
| <code>docs/platform-users/external-resources/aws/privatelink/manage-vpc-endpoint-service.md:219</code>                                                            | <code>oc -n &lt;namespace&gt; get svc &lt;openshift_service_name&gt; -o jsonpath='{.metadata.annotations}'</code>                                                                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/codecov/sop/pod-security.md:49</code>                                                                                                  | <code>oc get deployment codecov-api -n &lt;namespace&gt; -o jsonpath='{.spec.template.spec.containers[0].securityContext.runAsUser}'</code>                                                                                                                                                                                                                                                                                            |
| <code>docs/tenant-services/console.redhat.com/app-sops/export-service/database-disaster-recovery.md:98</code>                                                     | <code>oc get deployment/export-service-service -n export-service-prod -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'</code>                                                                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/console.redhat.com/app-sops/export-service/service-down-export-service-prod-export-service-service.md:80</code>                        | <code>oc get deployment/export-service-service -n export-service-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/console.redhat.com/app-sops/hcc/akamai-psk-rotation.md:118</code>                                                                      | <code>oc get secret akamai-shared-secret -n openshift-ingress -o jsonpath='{.data.token}' &#124; base64 -d; echo</code>                                                                                                                                                                                                                                                                                                                |
| <code>docs/tenant-services/console.redhat.com/app-sops/hcc/akamai-psk-rotation.md:119</code>                                                                      | <code>oc get secret akamai-shared-secret -n openshift-ingress -o jsonpath='{.data.token_alt}' &#124; base64 -d; echo</code>                                                                                                                                                                                                                                                                                                            |
| <code>docs/tenant-services/console.redhat.com/app-sops/hcc/east-west-gateway-setup.md:32</code>                                                                   | <code>oc get ingresscontroller default -n openshift-ingress-operator -o jsonpath='{.spec.defaultCertificate.name}'</code>                                                                                                                                                                                                                                                                                                              |
| <code>docs/tenant-services/console.redhat.com/app-sops/hcc/north-south-gateway-setup.md:33</code>                                                                 | <code>&#124; Cluster OIDC issuer URL &#124; &#96;spec.oidc_endpoint_url&#96; in &#96;data/openshift/&lt;CLUSTER_NAME&gt;/cluster.yml&#96; (populated automatically by the &#96;ocm-clusters&#96; integration). Alternatively, &#96;oc get authentication cluster -o jsonpath='{.spec.serviceAccountIssuer}'&#96; &#124; &#96;https://oidc.op1.openshiftapps.com/2l6ov2fofmvhveg6rdu1n35tepj13c6d&#96; &#124;</code>                    |
| <code>docs/tenant-services/console.redhat.com/app-sops/ingress/service-down-ingress-prod-ingress-service.md:79</code>                                             | <code>oc get deployment/ingress-service -n ingress-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/kessel/Inventory-Consumer-SOP.md:97</code>                                                                 | <code>oc get kctr hbi-outbox-connector -o jsonpath='{.status.connectorStatus}' &#124; jq</code>                                                                                                                                                                                                                                                                                                                                        |
| <code>docs/tenant-services/console.redhat.com/app-sops/kessel/Inventory-Consumer-SOP.md:102</code>                                                                | <code>oc get kctr hbi-outbox-connector -o jsonpath='{.status.connectorStatus}' &#124; jq</code>                                                                                                                                                                                                                                                                                                                                        |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-backend-service.md:93</code>                   | <code>oc get deployment/notifications-backend-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-email-service.md:87</code>           | <code>oc get deployment/notifications-connector-email-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                     |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-google-chat-service.md:84</code>     | <code>oc get deployment/notifications-connector-google-chat-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                               |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-microsoft-teams-service.md:84</code> | <code>oc get deployment/notifications-connector-microsoft-teams-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                           |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-pagerduty-service.md:87</code>       | <code>oc get deployment/notifications-connector-pagerduty-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-servicenow-service.md:87</code>      | <code>oc get deployment/notifications-connector-servicenow-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-slack-service.md:84</code>           | <code>oc get deployment/notifications-connector-slack-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                     |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-splunk-service.md:87</code>          | <code>oc get deployment/notifications-connector-splunk-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                    |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-connector-webhook-service.md:87</code>         | <code>oc get deployment/notifications-connector-webhook-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-engine-service.md:91</code>                    | <code>oc get deployment/notifications-engine-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                              |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-gw-service.md:86</code>                        | <code>oc get deployment/notifications-gw-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                  |
| <code>docs/tenant-services/console.redhat.com/app-sops/notifications/service-down-notifications-prod-notifications-recipients-resolver-service.md:88</code>       | <code>oc get deployment/notifications-recipients-resolver-service -n notifications-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/payload-tracker/service-down-payload-tracker-prod-payload-tracker-api.md:79</code>                         | <code>oc get deployment/payload-tracker-api -n payload-tracker-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                     |
| <code>docs/tenant-services/console.redhat.com/app-sops/rbac/sop-replication-failure.md:77</code>                                                                  | <code>oc get deployment rbac-rbac-kafka-consumer -n &lt;namespace&gt; -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="RBAC_KAFKA_CONSUMER_GROUP_ID")].value}'</code>                                                                                                                                                                                                                                                    |
| <code>docs/tenant-services/console.redhat.com/app-sops/scheduler/SchedulerHTTPErrorRateBurn.rst:72</code>                                                         | <code>- Pod restarts: &#96;&#96;oc get pods -n scheduler-prod -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].restartCount}{"\n"}{end}'&#96;&#96;</code>                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/console.redhat.com/app-sops/scheduler/SchedulerHTTPLatencyErrorBudgetBurn.rst:50</code>                                                | <code>- Check pod restarts: &#96;&#96;oc get pods -n scheduler-prod -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].restartCount}{"\n"}{end}'&#96;&#96;</code>                                                                                                                                                                                                                                       |
| <code>docs/tenant-services/console.redhat.com/app-sops/scheduler/database-disaster-recovery.md:102</code>                                                         | <code>oc get deployment/scheduler-api -n scheduler-prod -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'</code>                                                                                                                                                                                                                                                                                                           |
| <code>docs/tenant-services/console.redhat.com/app-sops/scheduler/database-disaster-recovery.md:103</code>                                                         | <code>oc get deployment/scheduler-worker -n scheduler-prod -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'</code>                                                                                                                                                                                                                                                                                                        |
| <code>docs/tenant-services/console.redhat.com/app-sops/sources/service-down-sources-prod-sources-api-svc.md:81</code>                                             | <code>oc get deployment/sources-api-svc -n sources-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/sources/service-down-sources-prod-sources-superkey-worker-svc.md:81</code>                                 | <code>oc get deployment/sources-superkey-worker-svc -n sources-prod -o jsonpath='{.spec.template.spec.containers[0].image}'</code>                                                                                                                                                                                                                                                                                                     |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsDataExporterServiceAbsent.rst:78</code>                                 | <code>oc get pods -l app=automation-analytics-data-exporter -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                          |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsDataExporterServiceAbsent.rst:110</code>                                | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-data-exporter -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                              |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorErrors.rst:68</code>                                 | <code>oc get deployment automation-analytics-etl-rollups-processor -o jsonpath='{.spec.replicas}'</code>                                                                                                                                                                                                                                                                                                                               |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorErrors.rst:99</code>                                 | <code>oc get pods -l app=automation-analytics-etl-rollups-processor -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                  |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorErrors.rst:139</code>                                | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-etl-rollups-processor -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorServiceAbsent.rst:57</code>                          | <code>oc get deployment automation-analytics-etl-rollups-processor -o jsonpath='{.spec.replicas}'</code>                                                                                                                                                                                                                                                                                                                               |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorServiceAbsent.rst:86</code>                          | <code>oc get pods -l app=automation-analytics-etl-rollups-processor -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                  |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsEtlRollupsProcessorServiceAbsent.rst:100</code>                         | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-etl-rollups-processor -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsFastAPIServiceAbsent.rst:85</code>                                      | <code>oc get pods -l app=automation-analytics-api-fastapi-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                         |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsFastAPIServiceAbsent.rst:117</code>                                     | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-api-fastapi-v2 -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsIngressAAPBillingServiceAbsent.rst:82</code>                            | <code>oc get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' &#124; grep -i oom</code>                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsIngressAAPBillingServiceAbsent.rst:113</code>                           | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-billing-processor-aap-billing-ingress -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsLowV2StrategyAdoption.rst:127</code>                                    | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-billing-processor-aap-billing-controller -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsPodDown.rst:87</code>                                                   | <code>oc get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' &#124; grep -i oom</code>                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsPodDown.rst:116</code>                                                  | <code>oc get deployment automation-analytics-etl-rollups-processor -o jsonpath='{.spec.replicas}'</code>                                                                                                                                                                                                                                                                                                                               |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsPodDown.rst:148</code>                                                  | <code>- Deployed: &#96;&#96;oc get deployment &lt;deployment-name&gt; -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                                         |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorAAPBillingServiceAbsent.rst:81</code>                          | <code>oc get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' &#124; grep -i oom</code>                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorAAPBillingServiceAbsent.rst:121</code>                         | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-billing-processor-aap-billing-controller -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorAAPEdaServiceAbsent.rst:79</code>                              | <code>oc get pods -l app=automation-analytics-processor-aap-eda -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorAAPEdaServiceAbsent.rst:121</code>                             | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-processor-aap-eda -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                          |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorServiceAbsent.rst:76</code>                                    | <code>oc get pods -l app=automation-analytics-processor-controller-v1 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsProcessorServiceAbsent.rst:118</code>                                   | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-processor-controller-v1 -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                    |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsRestarts.rst:81</code>                                                  | <code>oc get pod &lt;pod-name&gt; -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'</code>                                                                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsRestarts.rst:124</code>                                                 | <code>oc get pod &lt;pod-name&gt; -o jsonpath='{.spec.containers[*].resources.limits.memory}'</code>                                                                                                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsRollupsServiceAbsent.rst:87</code>                                      | <code>oc get pods -l app=automation-analytics-rollups-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/console.redhat.com/app-sops/tower-analytics/AutomationAnalyticsRollupsServiceAbsent.rst:119</code>                                     | <code>- Deployed: &#96;&#96;oc get deployment automation-analytics-rollups-v2 -o jsonpath='{.spec.template.spec.containers[0].image}'&#96;&#96;</code>                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/devlake/sop/connecting-to-db-via-port-forward.md:47</code>                                                                             | <code>PROXY_POD=$(oc get pods -n devlake-stage -l app=devlake-proxysql -o jsonpath='{.items[0].metadata.name}')</code>                                                                                                                                                                                                                                                                                                                 |
| <code>docs/tenant-services/osd-fleet-manager/sop/accessing-the-aws-account-of-a-cluster.md:66</code>                                                              | <code>export AWS_ACCESS_KEY_ID=$(oc get secrets ${CLUSTER}-account-creds -o jsonpath='{.data.aws_access_key_id}' &#124; base64 -d)</code>                                                                                                                                                                                                                                                                                              |
| <code>docs/tenant-services/osd-fleet-manager/sop/accessing-the-aws-account-of-a-cluster.md:67</code>                                                              | <code>export AWS_SECRET_ACCESS_KEY=$(oc get secrets ${CLUSTER}-account-creds -o jsonpath='{.data.aws_secret_access_key}' &#124; base64 -d)</code>                                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/osd-fleet-manager/sop/cleanup-openshift-adp-operator-ns.md:114</code>                                                                  | <code>oc get cloudstorage &lt;cloudstorage-name&gt; -n openshift-adp-operator -o jsonpath='{.metadata.finalizers}'</code>                                                                                                                                                                                                                                                                                                              |
| <code>docs/tenant-services/osd-fleet-manager/sop/fleet-upgrade-addon.md:133</code>                                                                                | <code>oc get mch -A -o jsonpath='{.items[0].status.currentVersion}'</code>                                                                                                                                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/osd-fleet-manager/sop/fleet-upgrade-addon.md:134</code>                                                                                | <code>oc get mce -A -o jsonpath='{.items[0].status.currentVersion}'</code>                                                                                                                                                                                                                                                                                                                                                             |
| <code>docs/tenant-services/pulp/sop/PulpCrashing.md:54</code>                                                                                                     | <code>oc get pods -n pulp-{env} -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}'</code>                                                                                                                                                                                                                                                                      |
| <code>docs/tenant-services/pulp/sop/PulpWorkersDown.md:143</code>                                                                                                 | <code>oc get pods -n pulp-{env} -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' &#124; grep -i oom</code>                                                                                                                                                                                                                                                   |
| <code>docs/tenant-services/rhel-lightspeed/sop/README.md:540</code>                                                                                               | <code>oc get pod &lt;pod&gt; -n &lt;namespace&gt; -o jsonpath='{.status.containerStatuses}' &#124; jq</code>                                                                                                                                                                                                                                                                                                                           |
| <code>docs/tenant-services/rhel-lightspeed/sop/README.md:678</code>                                                                                               | <code>oc get pod &lt;pod&gt; -n &lt;namespace&gt; -o jsonpath='{.status.containerStatuses}' &#124; jq</code>                                                                                                                                                                                                                                                                                                                           |
| <code>docs/tenant-services/rhel-lightspeed/sop/README.md:889</code>                                                                                               | <code>oc get pod &lt;pod&gt; -n &lt;namespace&gt; -o jsonpath='{.status.containerStatuses}' &#124; jq</code>                                                                                                                                                                                                                                                                                                                           |
| <code>docs/tenant-services/uhc/sop/ams/pod-restarts.md:89</code>                                                                                                  | <code>&#124; **CPU / throttling** &#124; &#96;oc top pods -n &lt;ns&gt; -l app=uhc-acct-mngr&#96; (or &#96;kubectl top&#96;). Limits: &#96;oc get deploy uhc-acct-mngr -n &lt;ns&gt; -o jsonpath='{.spec.template.spec.containers[*].resources}'&#96;. Throttling: see [Validation](#validation) PromQL. &#124; **OCM-10349**. Do not infer throttling from app log &#96;grep&#96;. Eng-only — **@ocm-ams-maintainers**. &#124;</code> |
| <code>docs/tenant-services/uhc/sop/ams/pod-restarts.md:112</code>                                                                                                 | <code>oc get pod -n &lt;ns&gt; &lt;pod-from-alert&gt; -o jsonpath='{range .status.containerStatuses[*]}{.name}{": "}{.restartCount}{" restarts\n"}{end}'</code>                                                                                                                                                                                                                                                                        |
| <code>docs/tenant-services/uhc/sop/ocm-clusters-service.md:458</code>                                                                                             | <code>-o jsonpath='{.spec.template.spec.containers[0].resources}' &#124; jq .</code>                                                                                                                                                                                                                                                                                                                                                   |
| <code>hack/clo-decommission.sh:46</code>                                                                                                                          | <code>OC_CURRENT_CLUSTER=$(oc config view -o jsonpath="{.contexts[?(@.name == \"${OC_CURRENT_CONTEXT}\")].context.cluster}")</code>                                                                                                                                                                                                                                                                                                    |
| <code>hack/clo-decommission.sh:47</code>                                                                                                                          | <code>OC_CLUSTER_API_URL=$(oc config view -o jsonpath="{.clusters[?(@.name == \"${OC_CURRENT_CLUSTER}\")].cluster.server}")</code>                                                                                                                                                                                                                                                                                                     |
| <code>hack/operations/platform-secret-checker.sh:5</code>                                                                                                         | <code>NAMESPACE="${NAMESPACE:-$(kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2&gt;/dev/null &#124;&#124; echo default)}"</code>                                                                                                                                                                                                                                                                         |
| <code>hack/operations/platform-secret-checker.sh:106</code>                                                                                                       | <code>rv=$(kubectl get secret "$s" -n "$NAMESPACE" -o jsonpath='{.metadata.resourceVersion}')</code>                                                                                                                                                                                                                                                                                                                                   |
| <code>hack/operations/platform-secret-checker.sh:107</code>                                                                                                       | <code>uid=$(kubectl get secret "$s" -n "$NAMESPACE" -o jsonpath='{.metadata.uid}')</code>                                                                                                                                                                                                                                                                                                                                              |
| <code>hack/operations/platform-secret-checker.sh:125</code>                                                                                                       | <code>rv=$(kubectl get configmap "$cm" -n "$NAMESPACE" -o jsonpath='{.metadata.resourceVersion}')</code>                                                                                                                                                                                                                                                                                                                               |
| <code>hack/operations/platform-secret-checker.sh:193</code>                                                                                                       | <code>done &lt; &lt;(kubectl get "$kind" -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2&gt;/dev/null)</code>                                                                                                                                                                                                                                                                                             |
| <code>hack/operations/platform-secret-checker.sh:215</code>                                                                                                       | <code>done &lt; &lt;(kubectl get "$kind" -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2&gt;/dev/null)</code>                                                                                                                                                                                                                                                                                             |

### textual reference; review context

| File and line                                                                                | Source text                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <code>data/app-interface/query-validations/change-type-secret-access-validation.yml:8</code> | <code>Validate that change types do not use overly permissive jsonPath selectors</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| <code>data/services/assisted-chat/cicd/saas-assisted-chat.yaml:47</code>                     | <code>- jsonpath: "$.realm_access.roles[*]"</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| <code>data/services/assisted-chat/cicd/saas-assisted-chat.yaml:51</code>                     | <code>- jsonpath: "$.org_id"</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| <code>data/services/assisted-chat/cicd/saas-assisted-chat.yaml:55</code>                     | <code>- jsonpath: "$.is_internal"</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| <code>data/services/assisted-chat/cicd/target/integration/assisted-chat.yaml:20</code>       | <code>- jsonpath: $.email</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| <code>data/services/assisted-chat/cicd/target/integration/assisted-chat.yaml:25</code>       | <code>- jsonpath: $.rh-org-id</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| <code>data/services/assisted-chat/cicd/target/production/assisted-chat.yaml:17</code>        | <code>- jsonpath: $.email</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| <code>data/services/assisted-chat/cicd/target/production/assisted-chat.yaml:22</code>        | <code>- jsonpath: $.email</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| <code>data/services/assisted-chat/cicd/target/stage/assisted-chat.yaml:22</code>             | <code>- jsonpath: $.email</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| <code>data/services/assisted-chat/cicd/target/stage/assisted-chat.yaml:27</code>             | <code>- jsonpath: $.rh-org-id</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| <code>docs/platform-users/ci-cd/continuous-delivery-in-app-interface.md:108</code>           | <code>- &#96;jsonPathSelectors&#96; - define json path selectors based on the &#96;namespace&#96; resource</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:17</code>                           | <code>All app-interface datafiles (and some resource files) follow a defined schema (e.g. [&#96;/app-interface/saas-file-2.yml&#96;](https://github.com/app-sre/qontract-schemas/blob/main/schemas/app-interface/saas-file-2.yml)) and are well structured documents. A change-type can use &#96;JSONPath&#96; expressions to select parts of such files.</code>                                                                                                                                                                                                                                                                                                                   |
| <code>docs/platform-users/repo-mechanics/change-types.md:32</code>                           | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:33</code>                           | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:39</code>                           | <code>The changes described by this changes-type can be found in the &#96;changes&#96; section. Following the &#96;qontract-reconcile&#96; provider pattern, selection mechanisms other than &#96;JSONPath&#96; can be supported in the future but the &#96;jsonPath&#96; provider is the only one supported right now. &#96;changes.jsonPathSelectors&#96; defines a list of &#96;JSONPath&#96; expressions that will be self-serviceable. In our example, it is everything under &#96;deployResources&#96;. You can learn more about JSONPath [here](https://goessner.net/articles/JsonPath/index.html)) and experiment with on this [playground](https://jsonpath.com/).</code> |
| <code>docs/platform-users/repo-mechanics/change-types.md:98</code>                           | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:100</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:106</code>                          | <code>The change-type defines [&#96;/openshift/cluster-1.yml&#96;](https://github.com/app-sre/qontract-schemas/blob/main/schemas/openshift/cluster-1.yml) as the &#96;contextSchema&#96; so it is valid to attach it to a cluster, but at the same time it mentiones [&#96;/openshift/namespace-1.yml&#96;](https://github.com/app-sre/qontract-schemas/blob/main/schemas/openshift/namespace-1.yml) as the &#96;changeSchema&#96;. In this example we will grant permissions on the entire namespace files, so we use the JSONPath &#96;$&#96; which represents the root of the document.</code>                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:156</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:157</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:175</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:176</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:181</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:182</code>                          | <code>jsonPathSelector: $.path</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| <code>docs/platform-users/repo-mechanics/change-types.md:185</code>                          | <code>The &#96;implicitOwnership&#96; section uses JSONPath expressions to extract approver references directly from the file being changed. In this example, &#96;$.path&#96; means the user referenced by the file path itself can approve changes to their own user file.</code>                                                                                                                                                                                                                                                                                                                                                                                                |
| <code>docs/platform-users/repo-mechanics/change-types.md:218</code>                          | <code>The difference to our previous example is in the &#96;where: backrefs&#96; declaration. It defines, that ownership is expanded from a namespace to all defaults files used in that namespace, additionally restricting it with a jsonpath expression in &#96;selector&#96;.</code>                                                                                                                                                                                                                                                                                                                                                                                           |
| <code>docs/platform-users/repo-mechanics/change-types.md:220</code>                          | <code>## Advanced example: JSONPaths filtering, macro expansion and conditional context selectors</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| <code>docs/platform-users/repo-mechanics/change-types.md:237</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:239</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:245</code>                          | <code>The &#96;context.selector&#96; will correctly extract the roles of a user and the &#96;jsonPathSelector&#96; makes sure approvers can only approve changes in the &#96;roles&#96; section of such a userfile. But the &#96;jsonPathSelector&#96; is too wide. It grants permissions to approve ALL changes to the roles of a user, not just for the role the change-type is bound to. We need to narrow down the selector and luckily JSONPath supports filtering.</code>                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:249</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:251</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:255</code>                          | <code>The new &#96;jsonPathSelectors&#96; uses the filter syntax &#96;?(@.field==value)&#96; combined with Jinja2 macro expansion. The variable &#96;ctx_file_path&#96; resolves to the role path this change-type is bound to. Therefore this JSONPath restricts change permissions to those entries of the &#96;roles&#96; array that represent the role the change-type is bound to. In other words: the approvers can only approve changes that mention their role.</code>                                                                                                                                                                                                     |
| <code>docs/platform-users/repo-mechanics/change-types.md:261</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:282</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:284</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>docs/platform-users/repo-mechanics/change-types.md:295</code>                          | <code>The &#96;contextSchema&#96; property is optional in this situation, because not all resource files adhere to a schema. If a resource file declares a schema and contains a structured document, it can be processed exactly the same way as datafiles and fine grained &#96;jsonPathSelectors&#96; can be used to describe the parts of the file that are covered under the change-type.</code>                                                                                                                                                                                                                                                                              |
| <code>docs/platform-users/repo-mechanics/change-types.md:297</code>                          | <code>Resource files that don't declare a schema or aren't structured documents can't use fine grained change selection within the file. The only available option for the &#96;jsonPathSelector&#96; is &#96;$&#96;, which covers basically the entire file and grants permission to approve arbitrary changes in the file.</code>                                                                                                                                                                                                                                                                                                                                                |
| <code>docs/platform-users/repo-mechanics/change-types.md:309</code>                          | <code>A single JSONPath selector **cannot traverse this chain** because &#96;$ref&#96; entries are not resolved in the bundle data. Each &#96;$ref&#96; in the bundle remains as a simple &#96;{"$ref": "/path/to/file"}&#96; object — the referenced file's content is not inlined.</code>                                                                                                                                                                                                                                                                                                                                                                                        |
| <code>docs/platform-users/repo-mechanics/change-types.md:327</code>                          | <code>- provider: jsonPath</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>docs/platform-users/repo-mechanics/change-types.md:329</code>                          | <code>jsonPathSelectors:</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| <code>resources/queries/change-type-secret-access-validation.graphql:7</code>                | <code>... on ChangeTypeChangeDetectorJsonPathProvider_v1 {</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| <code>resources/queries/change-type-secret-access-validation.graphql:9</code>                | <code>jsonPathSelectors</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| <code>resources/templates/change-type-secret-access-validation.j2:21</code>                  | <code>{%- for change in ct.changes if change.jsonPathSelectors %}</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| <code>resources/templates/change-type-secret-access-validation.j2:22</code>                  | <code>{%- for selector in change.jsonPathSelectors %}</code>                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

## Parsing exclusions and remaining verification

The following candidates could not be structurally parsed. Raw-text matches remain in the textual-reference audit; render/inspect these explicitly before claiming complete runtime coverage.

- `data/templating/templates/hcp-collection/saas-logs-event-collector-target.yml: embedded template: while scanning for the next token; recovered 1 selector lines textually`
- `data/templating/templates/hcp-collection/saas-logs-forwarder-target.yml: embedded template: while scanning for the next token; recovered 1 selector lines textually`
- `data/templating/templates/hcp-collection/saas-logs-token-refresher-target.yml: embedded template: while scanning for the next token; recovered 1 selector lines textually`
- `data/templating/templates/hcp-collection/saas-metrics-target.yml: embedded template: while scanning for the next token; recovered 1 selector lines textually`
- `data/templating/templates/hcp-collection/saas-rmo-config-target.yml: embedded template: while scanning for the next token; recovered 1 selector lines textually`
- `resources/observability/servicemonitors/glitchtip-jira-bridge.servicemonitor.yaml: while parsing a block mapping`
- `resources/observability/servicemonitors/glitchtip-worker.servicemonitor.yaml: while parsing a block mapping`
- `resources/services/configuration-anomaly-detection/cad-pd-secret-prod.selectorsyncset.yaml: while scanning for the next token`
- `resources/services/configuration-anomaly-detection/cad-pd-secret-stage.selectorsyncset.yaml: while scanning for the next token`
- `resources/services/mcs-custom-alerts/mcs-custom-alerts-pd-secret-stage.selectorsyncset.yaml: while scanning for the next token`
- `resources/skupper/v1/site-controller-deployment.yml: while scanning for the next token`

- Only parse acceptance is measured here. No production input was evaluated by the replacement engine.
- Render every affected template and fixture, including the HCP generators and GABI condition.
- Audit all shared Jinja call sites: OpenShift resource/Prometheus templates, template mechanism, SaaS target parameter and secret-path interpolation, external-resource output/secret formatting, ASG cloud-init, fleet labels, upgrade policies, and Prometheus tests.
- Tenant SaaS templates processed with `oc process`, Helm, or directory loading do not automatically receive these custom filters. `github()` returns data rather than recursively rendering it.
- Preserve existing filter names. Follow the milestone plan: M1 observes syntax failures and runtime result mismatches with `jsonpath-ng` still authoritative; M2 migrates queries and changes the default with `jsonpath-ng` fallback for unapproved differences; M3 removes `jsonpath-ng` after fallback is no longer needed. Runtime comparison belongs in the utility package and is additional to this static inventory. The snapshot counts and query catalog remain unchanged.
- Compare authorization, inclusion/exclusion sets, shard selection, pointers, and mutated/rendered resources in the implementation phase.
