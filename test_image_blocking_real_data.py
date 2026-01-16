#!/usr/bin/env python3
"""
Test script to verify imagePatternsBlockRules logic with real saas file data.
This simulates what would happen during deployment-time validation.
"""
import json
import sys
from pathlib import Path

# Add reconcile to path
sys.path.insert(0, str(Path(__file__).parent))

from unittest.mock import MagicMock, patch

from reconcile import queries
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.secret_reader import SecretReaderBase


class MockSecretReader(SecretReaderBase):
    """Mock secret reader for testing"""
    def _read(self, path: str, field: str, format: str | None, version: int | None) -> str:
        return "mock-secret"
    
    def _read_all(self, path: str, field: str, format: str | None, version: int | None) -> dict[str, str]:
        return {"mock": "secret"}


def test_real_saas_file(saas_file_name: str, env_name: str = "production"):
    """Test image blocking with a real saas file"""
    
    # Mock app-interface settings to return our imagePatternsBlockRules config
    settings = {
        "imagePatternsBlockRules": [
            {
                "environmentLabelSelector": {"type": "production"},
                "imagePatterns": ["quay.io/redhat-user-workloads"],
            }
        ]
    }
    
    with patch.object(queries, "get_app_interface_settings", return_value=settings):
        # Get real saas files
        saas_files = get_saas_files(name=saas_file_name, env_name=env_name)
        
        if not saas_files:
            print(f"❌ No saas files found matching name={saas_file_name}, env_name={env_name}")
            return
        
        saas_file = saas_files[0]
        print(f"✅ Found saas file: {saas_file.name}")
        print(f"   Path: {saas_file.path}")
        print(f"   Image patterns: {saas_file.image_patterns}")
        print()
        
        # Create SaasHerder
        secret_reader = MockSecretReader()
        saasherder = SaasHerder(
            [saas_file],
            secret_reader=secret_reader,
            thread_pool_size=1,
            integration="test",
            integration_version="test",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        
        # Check each production target
        print("Checking production targets...")
        print()
        
        for rt in saas_file.resource_templates:
            for target in rt.targets:
                if not target.namespace or not target.namespace.environment:
                    continue
                
                env_labels = target.namespace.environment.labels
                if isinstance(env_labels, str):
                    env_labels = json.loads(env_labels)
                
                is_production = env_labels and env_labels.get("type") == "production"
                
                if not is_production:
                    continue
                
                print(f"📦 Resource Template: {rt.name}")
                print(f"   Target: {target.namespace.name}")
                print(f"   Environment: {target.namespace.environment.name}")
                print(f"   Labels: {env_labels}")
                
                # Mock GitHub and get file contents to process template
                # For now, we'll just check what images would be used
                if target.images:
                    print(f"   Images directive:")
                    for img in target.images:
                        img_path = f"quay.io/{img.org.name}/{img.name}"
                        print(f"     - {img_path}")
                        if img_path.startswith("quay.io/redhat-user-workloads"):
                            print(f"       ⚠️  BLOCKED: This image would be flagged!")
                
                if target.parameters:
                    target_params = target.parameters
                    if isinstance(target_params, str):
                        target_params = json.loads(target_params)
                    
                    print(f"   Parameters with image-like values:")
                    for key, value in target_params.items():
                        if isinstance(value, str) and (
                            value.startswith("quay.io/") or value.startswith("registry.")
                        ):
                            print(f"     {key}: {value}")
                            if value.startswith("quay.io/redhat-user-workloads"):
                                print(f"       ⚠️  BLOCKED: This image would be flagged!")
                
                # Check imagePatterns fallback
                if saas_file.image_patterns:
                    has_redhat_user_workloads = any(
                        img.startswith("quay.io/redhat-user-workloads")
                        for img in saas_file.image_patterns
                    )
                    if has_redhat_user_workloads:
                        if not target.images and not any(
                            isinstance(v, str) and (
                                v.startswith("quay.io/") or v.startswith("registry.")
                            ) and not v.startswith("quay.io/redhat-user-workloads")
                            for v in (target.parameters or {}).values()
                            if isinstance(target.parameters, dict)
                        ):
                            print(f"   ⚠️  FALLBACK CHECK: redhat-user-workloads in imagePatterns")
                            print(f"      (Would be flagged if no compliant override found)")
                
                print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_image_blocking_real_data.py <saas-file-name> [env-name]")
        print()
        print("Example:")
        print("  python test_image_blocking_real_data.py assisted-installer-events production")
        sys.exit(1)
    
    saas_file_name = sys.argv[1]
    env_name = sys.argv[2] if len(sys.argv) > 2 else "production"
    
    print(f"Testing saas file: {saas_file_name}")
    print(f"Environment: {env_name}")
    print("=" * 60)
    print()
    
    test_real_saas_file(saas_file_name, env_name)
