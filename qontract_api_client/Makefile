.PHONY: generate-client
generate-client:
	@rm -rf qontract_api_client/*
	uv tool run openapi-python-client==0.27.1 generate \
		--url=http://localhost:8080/docs/openapi.json \
		--meta=none \
		--output-path=qontract_api_client \
		--custom-template-path=openapi_python_client_templates \
		--overwrite
	@touch qontract_api_client/py.typed
