
# Skupper

* single site installation of skupper aren't supported


# Debug

* `skupper link status`

```shell
# skupper-example-01

Links created from this site:
-------------------------------
Link skupper-network-01-appint-ex-01-skupper-example-01 not active
Link skupper-network-01-appint-ex-01-skupper-example-02 is active

Currently active links from other sites:
----------------------------------------
A link from the namespace skupper-example-02 on site skupper-network-01-appint-ex-01-skupper-example-02(aeca980b-f39d-4550-a9eb-ee404aae52dd) is active
A link from the namespace skupper-example-03 on site skupper-network-01-appint-ex-01-skupper-example-03(d90c2518-848d-46eb-a944-203e896181ba) is active

# skupper-example-02

Links created from this site:
-------------------------------
Link skupper-network-01-appint-ex-01-skupper-example-01 is active
Link skupper-network-01-appint-ex-01-skupper-example-02 not active

Currently active links from other sites:
----------------------------------------
A link from the namespace skupper-example-01 on site skupper-network-01-appint-ex-01-skupper-example-01(463a4e2a-bd09-4e24-8e57-b3c2ee6899c1) is active
A link from the namespace skupper-example-03 on site skupper-network-01-appint-ex-01-skupper-example-03(d90c2518-848d-46eb-a944-203e896181ba) is active


# skupper-example-03

Links created from this site:
-------------------------------
Link skupper-network-01-appint-ex-01-skupper-example-01 not active
Link skupper-network-01-appint-ex-01-skupper-example-02 is active

Currently active links from other sites:
----------------------------------------
There are no active links
```

Note: Do not trust the link "active or "not active" status. It is not reliable. The only way to know if the link is active is to check the incoming connections.
