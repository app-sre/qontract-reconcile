from unittest import TestCase
import reconcile.terraform_resources as integ


class TestSupportFunctions(TestCase):

    def test_filter_no_managed_tf_resources(self):
        ra = {'account': 'a'}
        ns1 = {'managedTerraformResources': False, 'terraformResources': []}
        ns2 = {'managedTerraformResources': True, 'terraformResources': [ra]}
        namespaces = [ns1, ns2]
        filtered = integ.filter_tf_namespaces(namespaces, None)
        self.assertEqual(filtered, [ns2])

    def test_filter_tf_namespaces_with_account_name(self):
        ra = {'account': 'a'}
        rb = {'account': 'b'}
        ns1 = {'managedTerraformResources': True, 'terraformResources': [ra]}
        ns2 = {'managedTerraformResources': True, 'terraformResources': [rb]}
        namespaces = [ns1, ns2]
        filtered = integ.filter_tf_namespaces(namespaces, 'a')
        self.assertEqual(filtered, [ns1])

    def test_filter_tf_namespaces_without_account_name(self):
        ra = {'account': 'a'}
        rb = {'account': 'b'}
        ns1 = {'managedTerraformResources': True, 'terraformResources': [ra]}
        ns2 = {'managedTerraformResources': True, 'terraformResources': [rb]}
        namespaces = [ns1, ns2]
        filtered = integ.filter_tf_namespaces(namespaces, None)
        self.assertEqual(filtered, namespaces)
