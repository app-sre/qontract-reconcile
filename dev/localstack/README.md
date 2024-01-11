# LocalStack

LocalStack [doc](https://docs.localstack.cloud/overview/)

## Start LocalStack

```bash
$ make localstack
```

## Access LocalStack

Use AWS CLI, [doc](https://docs.localstack.cloud/user-guide/integrations/aws-cli/)

```bash
$ aws --endpoint-url=http://localhost:4566 s3 ls

$ aws --endpoint-url=http://localhost:4566 s3 ls s3://app-interface-state --recursive
```

## Use with qontract cli

```bash
$ export $(cat .env.local | xargs)

$ qontract-cli --config config.toml state set terraform-resources k v

$ qontract-cli --config config.toml state get terraform-resources k
```
