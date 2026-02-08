"""Hub API client for psa tools."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class HubClient:
    """Client for interacting with psaOps Hub API."""

    base_url: str
    timeout: int = 30

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make HTTP request to hub API."""
        url = f"{self.base_url.rstrip('/')}{path}"

        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url = f"{url}?{query}"

        body = None
        if data:
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            try:
                error_data = json.loads(error_body)
                detail = error_data.get("detail", str(e))
                raise HubError(f"{detail}", status_code=e.code)
            except json.JSONDecodeError:
                raise HubError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise HubError(f"Connection failed: {e.reason}")

    def health(self) -> dict:
        """Check hub health."""
        return self._request("GET", "/health")

    def list_environments(self) -> list[dict]:
        """List all environments."""
        return self._request("GET", "/api/v1/environments")

    def get_environment(self, env_id: str) -> dict:
        """Get environment by ID."""
        return self._request("GET", f"/api/v1/environments/{env_id}")

    def list_nodes(self) -> list[dict]:
        """List all nodes."""
        return self._request("GET", "/api/v1/nodes")

    def get_node_by_hostname(self, hostname: str) -> Optional[dict]:
        """Find node by hostname."""
        nodes = self.list_nodes()
        for node in nodes:
            if node.get("hostname") == hostname or node.get("name") == hostname:
                return node
        return None

    def create_node(
        self,
        name: str,
        hostname: str,
        environment_id: str,
        os_type: str = "Linux",
        **kwargs: Any,
    ) -> dict:
        """Create a new node."""
        data = {
            "name": name,
            "hostname": hostname,
            "environment_id": environment_id,
            "os_type": os_type,
            **kwargs,
        }
        return self._request("POST", "/api/v1/nodes", data=data)

    def ingest_scan(
        self,
        hostname: str,
        domains: list[dict],
        environment_id: Optional[str] = None,
        scan_source: str = "psa-discover",
    ) -> dict:
        """Push discovery results to hub."""
        data = {
            "hostname": hostname,
            "domains": domains,
            "scan_source": scan_source,
        }
        params = {"environment_id": environment_id} if environment_id else None
        return self._request("POST", "/api/v1/scan/ingest", data=data, params=params)

    def get_tier_yaml(self, tier: str) -> str:
        """Get tier-level YAML from hub."""
        url = f"{self.base_url.rstrip('/')}/api/v1/yaml/tier/{tier}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise HubError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise HubError(f"Connection failed: {e.reason}")

    def get_environment_yaml(self, environment: str) -> str:
        """Get environment-level YAML from hub."""
        url = f"{self.base_url.rstrip('/')}/api/v1/yaml/environment/{environment}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise HubError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise HubError(f"Connection failed: {e.reason}")

    def get_node_config(self, node_id: str, environment_id: Optional[str] = None) -> str:
        """Get psa config YAML for a node.

        Args:
            node_id: UUID of the node
            environment_id: Optional environment UUID (required if node has no domains)

        Returns:
            YAML config string ready to write to ~/.config/psa/config.yaml
        """
        url = f"{self.base_url.rstrip('/')}/api/v1/nodes/{node_id}/psa-config"
        if environment_id:
            url += f"?environment_id={environment_id}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise HubError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise HubError(f"Connection failed: {e.reason}")

    def sync_yaml(self, tier: Optional[str] = None, environments: Optional[str] = None) -> dict:
        """Sync YAMLs from hub. Returns dict of {path: yaml_content}."""
        params = {}
        if tier:
            params['tier'] = tier
        if environments:
            params['environments'] = environments
        return self._request("GET", "/api/v1/yaml/sync", params=params)

    def import_yaml(
        self,
        level: str,
        level_key: str,
        yaml_content: str,
        replace_all: bool = True
    ) -> dict:
        """Import YAML content to hub.

        Args:
            level: "tier" or "environment"
            level_key: Tier name or environment name
            yaml_content: Raw YAML content
            replace_all: If True, replace existing config values

        Returns:
            Import result with counts
        """
        url = f"{self.base_url.rstrip('/')}/api/v1/yaml/import?level={level}&level_key={level_key}&replace_all={replace_all}"

        # Encode YAML as body
        body = yaml_content.encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "text/plain"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            try:
                error_data = json.loads(error_body)
                detail = error_data.get("detail", str(e))
                raise HubError(f"{detail}", status_code=e.code)
            except json.JSONDecodeError:
                raise HubError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise HubError(f"Connection failed: {e.reason}")

# REMOVED: generate_from_environment method
# Deferred to future iteration - see issue #56

# REMOVED: generate_from_environments method (bulk generation)
# Deferred to issue #49 for future implementation


class HubError(Exception):
    """Error from hub API."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def get_hostname() -> str:
    """Get current hostname."""
    return socket.gethostname()


def get_ip_address() -> str:
    """Get primary IP address of this host."""
    try:
        # Connect to external address to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())
