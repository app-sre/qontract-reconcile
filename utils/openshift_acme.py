ACME_DEPLOYMENT = """
kind: Deployment
apiVersion: apps/v1
metadata:
  name: %(deployment_name)s
  labels:
    app: openshift-acme
spec:
  replicas: 1
  selector:
    matchLabels:
      app: openshift-acme
  strategy:
    type: RollingUpdate
  template:
    metadata:
      labels:
        app: openshift-acme
    spec:
      containers:
      - image: %(image)s
        imagePullPolicy: Always
        name: openshift-acme
        resources:
          limits:	
            cpu: 50m	
            memory: 100Mi	
          requests:	
            cpu: 5m	
            memory: 50Mi
        args:
        - --exposer-image=quay.io/tnozicka/openshift-acme:exposer
        - --loglevel=4
        - --namespace=acme-controller
      serviceAccountName: %(serviceaccount_name)s
"""

ACME_SERVICEACCOUNT = """
kind: ServiceAccount
apiVersion: v1
metadata:
  name: %(serviceaccount_name)s
  labels:
    app: openshift-acme
"""

ACME_ROLE = """
apiVersion: %(role_api_version)s
kind: Role
metadata:
  name: %(role_name)s
  labels:
    app: openshift-acme
rules:
- apiGroups:
  - "route.openshift.io"
  resources:
  - routes
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
  - deletecollection

- apiGroups:
  - "route.openshift.io"
  resources:
  - routes/custom-host
  verbs:
  - create

- apiGroups:
  - ""
  resources:
  - configmaps
  - services
  - secrets
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch

- apiGroups:
  - "apps"
  resources:
  - replicasets
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
"""

ACME_ROLEBINDING = """
apiVersion: %(rolebinding_api_version)s
groupNames: null
kind: RoleBinding
metadata:
  name: %(rolebinding_name)s
roleRef:
  kind: Role
  name: %(role_name)s
  namespace: %(namespace_name)s
subjects:
- kind: ServiceAccount
  name: %(serviceaccount_name)s
"""

ACME_CONFIGMAP = """
kind: ConfigMap
apiVersion: v1
metadata:
  name: letsencrypt-live
  annotations:
    "acme.openshift.io/priority": "100"
  labels:
    managed-by: "openshift-acme"
    type: "CertIssuer"
data:
  "cert-issuer.types.acme.openshift.io": '{"type":"ACME","acmeCertIssuer":{"directoryUrl":"https://acme-v02.api.letsencrypt.org/directory"}}'
"""