ACME_DEPLOYMENT = """
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
  name: {{ deployment_name }}
  labels:
    app: openshift-acme
spec:
  progressDeadlineSeconds: 600
  replicas: 1
  revisionHistoryLimit: 10
  selector:
    matchLabels:
      app: openshift-acme
  strategy:
    type: Recreate
  template:
    metadata:
      creationTimestamp: null
      labels:
        app: openshift-acme
    spec:
      containers:
      - env:
        - name: OPENSHIFT_ACME_EXPOSER_IP
          valueFrom:
            fieldRef:
              apiVersion: v1
              fieldPath: status.podIP
        - name: OPENSHIFT_ACME_ACMEURL
          value: 'https://acme-v01.api.letsencrypt.org/directory'
        - name: OPENSHIFT_ACME_LOGLEVEL
          value: '4'
        - name: OPENSHIFT_ACME_NAMESPACE
          valueFrom:
            fieldRef:
              apiVersion: v1
              fieldPath: metadata.namespace
        image: {{ image }}
        imagePullPolicy: Always
        name: openshift-acme
        ports:
        - containerPort: 5000
          protocol: TCP
        resources:
          limits:
            cpu: 50m
            memory: 100Mi
          requests:
            cpu: 5m
            memory: 50Mi
        terminationMessagePath: /dev/termination-log
        terminationMessagePolicy: File
        volumeMounts:
        - mountPath: /dapi
          name: podinfo
          readOnly: true
      dnsPolicy: ClusterFirst
      restartPolicy: Always
      schedulerName: default-scheduler
      securityContext: {}
      serviceAccount: {{ serviceaccount_name }}
      serviceAccountName: {{ serviceaccount_name }}
      terminationGracePeriodSeconds: 30
      volumes:
      - name: podinfo
        downwardAPI:
          defaultMode: 420
          items:
          - path: labels
            fieldRef:
              apiVersion: v1
              fieldPath: metadata.labels
"""

ACME_SERVICEACCOUNT = """
kind: ServiceAccount
apiVersion: v1
metadata:
  name: {{ serviceaccount_name }}
  labels:
    app: openshift-acme
"""

ACME_ROLE = """
apiVersion: {{ role_api_version }}
kind: Role
metadata:
  name: {{ role_name }}
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

- apiGroups:
  - "route.openshift.io"
  resources:
  - routes/custom-host
  verbs:
  - create

- apiGroups:
  - ""
  resources:
  - services
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch

- apiGroups:
  - ""
  resources:
  - secrets
  {% if acme_secrets %}
  resourceNames:
  {% for acme_secret in acme_secrets %}
  - {{ acme_secret }}
  {% endfor %}
  {% endif %}
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
apiVersion: {{ rolebinding_api_version }}
groupNames: null
kind: RoleBinding
metadata:
  name: {{ rolebinding_name }}
roleRef:
  kind: Role
  name: {{ role_name }}
  namespace: {{ namespace_name }}
subjects:
- kind: ServiceAccount
  name: {{ serviceaccount_name }}
"""
