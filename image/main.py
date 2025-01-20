from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Log level
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("controller.log"), logging.StreamHandler()]
)
logger = logging.getLogger("Neo4jController")


class Controller(BaseHTTPRequestHandler):
    def sync(self, parent, children):
        """
        Synchronizes resources for a Neo4jCluster. Generates the desired resources including
        ServiceAccount, PersistentVolume, PersistentVolumeClaim, Deployment, and Service.
        """
        try:
            logger.info("Starting sync process.")
            logger.debug(f"Received parent object: {json.dumps(parent, indent=2)}")
            logger.debug(f"Received children list: {json.dumps(children, indent=2)}")

            # Extract properties from the parent spec
            cluster_name = parent.get("metadata", {}).get("name", "neo4j-cluster")
            namespace = parent.get("metadata", {}).get("namespace", "default")
            replicas = parent.get("spec", {}).get("coreReplicas", 1)
            admin_password = parent.get("spec", {}).get("adminPassword", "")
            storage_size = parent.get("spec", {}).get("persistence", {}).get("size", "50Gi")
            storage_class = parent.get("spec", {}).get("persistence", {}).get("storageClass", "")
            service_type = parent.get("spec", {}).get("service", {}).get("type", "ClusterIP")
            service_ports = parent.get("spec", {}).get("service", {}).get("ports", [])

            # Log extracted configuration values
            logger.debug(f"Parsed Cluster Name: {cluster_name}")
            logger.debug(f"Parsed Namespace: {namespace}")
            logger.debug(f"Parsed Replicas: {replicas}")
            logger.debug(f"Parsed Admin Password: {admin_password}")
            logger.debug(f"Parsed Storage Size: {storage_size}")
            logger.debug(f"Parsed Service Type: {service_type}")
            logger.debug(f"Parsed Service Ports: {json.dumps(service_ports)}")
            logger.debug(f"Parsed Storage Class: {storage_class}")

            # Validate admin_password (in case it contains unsafe characters)
            if not admin_password:
                logger.error("Admin password is not provided in the spec.")
                raise ValueError("Admin password is not provided in the spec.")
            if '/' in admin_password:
                logger.error("Password contains illegal character '/'. Please ensure it's a valid password.")
                raise ValueError("Password contains illegal character '/'.")

            # Define desired resources
            logger.info("Defining desired resource configurations...")

            service_account = {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {"name": f"{cluster_name}-service-account", "namespace": namespace}
            }
            logger.debug(f"Defined ServiceAccount: {json.dumps(service_account, indent=2)}")

            persistent_volume = {
                "apiVersion": "v1",
                "kind": "PersistentVolume",
                "metadata": {"name": f"{cluster_name}-pv"},
                "spec": {
                    "capacity": {"storage": storage_size},
                    "accessModes": ["ReadWriteOnce"],
                    "hostPath": {"path": f"/mnt/data/{cluster_name}"},
                    "storageClassName": storage_class
                }
            }
            logger.debug(f"Defined PersistentVolume: {json.dumps(persistent_volume, indent=2)}")

            persistent_volume_claim = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": f"{cluster_name}-pvc", "namespace": namespace},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": storage_size}},
                    "storageClassName": storage_class
                }
            }
            logger.debug(f"Defined PersistentVolumeClaim: {json.dumps(persistent_volume_claim, indent=2)}")

            deployment = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": f"{cluster_name}-deployment", "namespace": namespace},
                "spec": {
                    "replicas": replicas,
                    "selector": {"matchLabels": {"app": cluster_name}},
                    "template": {
                        "metadata": {"labels": {"app": cluster_name}},
                        "spec": {
                            "serviceAccountName": f"{cluster_name}-service-account",
                            "containers": [{
                                "name": "neo4j",
                                "image": "neo4j:4.4.9",
                                "env": [{"name": "NEO4J_AUTH", "value": f"neo4j/{admin_password}"}],
                                "ports": [{"containerPort": port["targetPort"]} for port in service_ports],
                                "volumeMounts": [{"name": "neo4j-data", "mountPath": "/data"}]
                            }],
                            "volumes": [{
                                "name": "neo4j-data",
                                "persistentVolumeClaim": {"claimName": f"{cluster_name}-pvc"}
                            }]
                        }
                    }
                }
            }
            logger.debug(f"Defined Deployment: {json.dumps(deployment, indent=2)}")

            service = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": f"{cluster_name}-service", "namespace": namespace},
                "spec": {
                    "type": service_type,
                    "ports": service_ports,
                    "selector": {"app": cluster_name}
                }
            }
            logger.debug(f"Defined Service: {json.dumps(service, indent=2)}")

            # Desired status
            desired_status = {
                "replicas": replicas,
                "storageSize": storage_size,
                "status": "Successfully synchronized resources."
            }
            logger.info("Resource definitions completed successfully.")
            logger.debug(f"Desired status: {json.dumps(desired_status, indent=2)}")

            children = [service_account, persistent_volume, persistent_volume_claim, deployment, service]
            logger.info("Resources synchronization complete. Returning results.")
            return {"status": desired_status, "children": children}

        except Exception as e:
            logger.error(f"An error occurred during synchronization: {e}", exc_info=True)
            raise

    def do_POST(self):
        """
        Handles POST requests from the Kubernetes Metacontroller.
        """
        try:
            logger.info("Received a POST request.")
            content_length = int(self.headers.get("Content-Length", 0))
            request_data = self.rfile.read(content_length)
            logger.debug(f"Raw POST data: {request_data.decode()}")

            observed = json.loads(request_data)
            logger.debug(f"Parsed observed object: {json.dumps(observed, indent=2)}")

            desired = self.sync(observed["parent"], observed.get("children", []))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(desired).encode())
            logger.info("POST response sent successfully.")

        except Exception as e:
            logger.error(f"An error occurred while handling the POST request: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        """
        Handles GET requests for readiness and liveness probes.
        """
        logger.info(f"Received GET request for path: {self.path}")
        if self.path == "/readiness":
            logger.info("Readiness probe check passed.")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready"}).encode())
        else:
            logger.warning(f"Unhandled GET request for path: {self.path}")
            self.send_response(404)
            self.end_headers()


def run(server_class=HTTPServer, handler_class=Controller, port=8081):
    """
    Starts the HTTP server for the controller.
    """
    logger.info(f"Starting Neo4j controller server on port {port}...")
    server_address = ("", port)
    httpd = server_class(server_address, handler_class)
    logger.info("Controller server is now running. Awaiting requests.")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
