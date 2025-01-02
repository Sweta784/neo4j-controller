from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from kubernetes import client, config, utils

class Controller(BaseHTTPRequestHandler):
    def sync(self, parent, children):
        """
        The main sync logic. It builds the desired resources (PV, PVC, Deployment, and Service)
        based on the parent Neo4jCluster specification.
        """
        # Extract properties from the parent spec (Neo4jCluster)
        cluster_name = parent.get("metadata", {}).get("name", "neo4j-cluster")
        replicas = parent.get("spec", {}).get("replicas", 1)
        storage_size = parent.get("spec", {}).get("storageSize", "50Gi")
        service_type = parent.get("spec", {}).get("service", {}).get("type", "ClusterIP")
        service_ports = parent.get("spec", {}).get("service", {}).get("ports", [])

        # Generate PV (Persistent Volume)
        pv = {
            "apiVersion": "v1",
            "kind": "PersistentVolume",
            "metadata": {
                "name": f"{cluster_name}-pv"
            },
            "spec": {
                "capacity": {
                    "storage": storage_size
                },
                "accessModes": ["ReadWriteOnce"],
                "hostPath": {
                    "path": f"/mnt/data/{cluster_name}"
                }
            }
        }

        # Generate PVC (Persistent Volume Claim)
        pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": f"{cluster_name}-pvc"
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {
                    "requests": {
                        "storage": storage_size
                    }
                },
                "volumeName": f"{cluster_name}-pv"
            }
        }

        # Generate the Deployment (Pod) for Neo4j
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": f"{cluster_name}-deployment"
            },
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {
                        "app": "neo4j"
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": "neo4j"
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "neo4j",
                                "image": "neo4j:4.4",
                                "env": [
                                    {
                                        "name": "NEO4J_AUTH",
                                        "value": "neo4j/test"
                                    }
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "neo4j-data",
                                        "mountPath": "/data"
                                    }
                                ]
                            }
                        ],
                        "volumes": [
                            {
                                "name": "neo4j-data",
                                "persistentVolumeClaim": {
                                    "claimName": f"{cluster_name}-pvc"
                                }
                            }
                        ]
                    }
                }
            }
        }

        # Generate Service to expose Neo4j
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"{cluster_name}-service"
            },
            "spec": {
                "type": service_type,
                "ports": service_ports,
                "selector": {
                    "app": "neo4j"
                }
            }
        }

        # Define the desired status based on the parent spec and children (resources)
        desired_status = {
            "pods": replicas,
            "storage": storage_size,
            "status": "Successfully calculated desired state"
        }

        # List the desired resources (children)
        children = [
            {"apiVersion": "v1", "kind": "PersistentVolume", "metadata": pv["metadata"], "spec": pv["spec"]},
            {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": pvc["metadata"], "spec": pvc["spec"]},
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": deployment["metadata"], "spec": deployment["spec"]},
            {"apiVersion": "v1", "kind": "Service", "metadata": service["metadata"], "spec": service["spec"]}
        ]

        # Return the desired state and the list of child resources
        return {"status": desired_status, "children": children}

    def do_POST(self):
        """
        Handle the POST request from Metacontroller. It reads the observed state,
        calls sync() to get the desired state, and returns the response.
        """
        try:
            # Read the incoming JSON request
            observed = json.loads(self.rfile.read(int(self.headers.get("content-length"))))

            # Get the desired state based on the parent (Neo4jCluster) spec
            desired = self.sync(observed["parent"], observed["children"])

            # Send the response back to Metacontroller
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(desired).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            error_msg = {"error": f"Failed to process request: {str(e)}"}
            self.wfile.write(json.dumps(error_msg).encode())

    def do_GET(self):
        """
        Handle GET requests for readiness checks.
        """
        if self.path == '/readiness':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run(server_class=HTTPServer, handler_class=Controller, port=8081):
    """
    Start the webhook HTTP server to handle requests from Metacontroller.
    """
    server_address = ("", port)
    httpd = server_class(server_address, handler_class)
    print(f"Starting webhook server on port {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run(port=8081)
