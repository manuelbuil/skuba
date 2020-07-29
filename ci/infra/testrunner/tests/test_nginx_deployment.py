import logging
import pytest
import requests
import time

INGRESS_HTTPBIN = ("""
---
apiVersion: networking.k8s.io/v1beta1
kind: Ingress
metadata:
  name: mytest-ingress
  namespace: default
  annotations:
    kubernetes.io/ingress.class: nginx
    ingress.kubernetes.io/ssl-passthrough: "false"    
    nginx.ingress.kubernetes.io/secure-backends: "false"
spec:
  rules:
  - host: httpbin.example.com
    http:
      paths:
      - path: /status
        backend:
          serviceName: httpbin
          servicePort: 8000
EOF
""")


@pytest.mark.pr
def test_nginx_deployment(deployment, platform, skuba, kubectl):
    logger = logging.getLogger("testrunner")
    workers = skuba.num_of_nodes("worker")
    kubectl.run_kubectl("create deployment nginx --image=nginx:stable-alpine")
    kubectl.run_kubectl("scale deployment nginx --replicas={replicas}".format(replicas=workers))
    kubectl.run_kubectl("expose deployment nginx --port=80 --type=NodePort")
    kubectl.run_kubectl("wait --for=condition=available deploy/nginx --timeout=3m")
    readyReplicas = kubectl.run_kubectl("get deployment/nginx -o jsonpath='{ .status.readyReplicas }'")

    assert int(readyReplicas) == workers

    nodePort = kubectl.run_kubectl("get service/nginx -o jsonpath='{ .spec.ports[0].nodePort }'")

    assert 30000 <= int(nodePort) <= 32767

    wrk_idx = 0
    ip_addresses = platform.get_nodes_ipaddrs("worker")

    url = "{protocol}://{ip}:{port}{path}".format(protocol="http", ip=str(ip_addresses[wrk_idx]), port=str(nodePort), path="/")
    r = requests.get(url)

    assert "Welcome to nginx" in r.text

    logger.info("Deploy httpbin")
    kubectl.run_kubectl("create -f https://raw.githubusercontent.com/istio/istio/release-1.5/samples/httpbin/httpbin.yaml")
    
    logger.info("Create the ingress config")
    kubectl.run_kubectl("apply -f - << EOF " + INGRESS_HTTPBIN)

    # Wait for config to be digested by nginx ingress
    time.sleep(60)

    url2 = "{protocol}://{ip}:{port}{path}".format(protocol="http", ip=str(ip_addresses[wrk_idx]), port=str(nodePort), path="/status/200")
    r = requests.get(url2, headers={'host': 'httpbin.example.com'})

    assert 200 == r.status_code

    # Cleanup
    kubectl.run_kubectl("delete -f https://raw.githubusercontent.com/istio/istio/release-1.5/samples/httpbin/httpbin.yaml")
    kubectl.run_kubectl("delete --wait --timeout=60s service/nginx")
    kubectl.run_kubectl("delete --wait --timeout=60s deployments/nginx")

    with pytest.raises(Exception):
        kubectl.run_kubectl("get service/nginx")

    with pytest.raises(Exception):
        kubectl.run_kubectl("get deployments/nginx")
