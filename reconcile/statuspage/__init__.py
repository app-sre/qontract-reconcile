from reconcile.statuspage import atlassian
from reconcile.statuspage.page import register_provider

# Status page providers are registered here to prevent all kinds of cyclic imports.
register_provider(atlassian.PROVIDER_NAME, atlassian.init_provider_for_page)
