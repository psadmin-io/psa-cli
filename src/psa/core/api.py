"""PSA-OPS API client for psa tools."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class ApiClient:
    """Client for interacting with psa-ops API."""

    base_url: str
    timeout: int = 30

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make HTTP request to PSA-OPS API."""
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
                raise ApiError(f"{detail}", status_code=e.code)
            except json.JSONDecodeError:
                raise ApiError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection failed: {e.reason}")

    def health(self) -> dict:
        """Check API health."""
        return self._request("GET", "/api/health")

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

    def update_node(self, node_id: str, **kwargs: Any) -> dict:
        """Update an existing node via PATCH.

        Args:
            node_id: UUID of the node
            **kwargs: Fields to update (e.g. ps_role="mid")

        Returns:
            Updated node dict
        """
        data = {k: v for k, v in kwargs.items() if v is not None}
        return self._request("PATCH", f"/api/v1/nodes/{node_id}", data=data)

    def ingest_scan(
        self,
        hostname: str,
        domains: list[dict],
        environment_id: Optional[str] = None,
        scan_source: str = "psa-discover",
    ) -> dict:
        """Push discovery results to PSA-OPS."""
        data = {
            "hostname": hostname,
            "domains": domains,
            "scan_source": scan_source,
        }
        params = {"environment_id": environment_id} if environment_id else None
        return self._request("POST", "/api/v1/scan/ingest", data=data, params=params)

    def get_tier_yaml(self, tier: str) -> str:
        """Get tier-level YAML from PSA-OPS."""
        url = f"{self.base_url.rstrip('/')}/api/v1/yaml/tier/{tier}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise ApiError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection failed: {e.reason}")

    def get_environment_yaml(self, environment: str) -> str:
        """Get environment-level YAML from PSA-OPS."""
        url = f"{self.base_url.rstrip('/')}/api/v1/yaml/environment/{environment}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise ApiError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection failed: {e.reason}")

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
            raise ApiError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection failed: {e.reason}")

    def sync_yaml(self, tier: Optional[str] = None, environments: Optional[str] = None) -> dict:
        """Sync YAMLs from PSA-OPS. Returns dict of {path: yaml_content}."""
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
        """Import YAML content to PSA-OPS.

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
                raise ApiError(f"{detail}", status_code=e.code)
            except json.JSONDecodeError:
                raise ApiError(f"HTTP {e.code}: {error_body or str(e)}", status_code=e.code)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection failed: {e.reason}")

    def list_domains(
        self,
        name: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> List[dict]:
        """List domains, optionally filtered by name and/or node."""
        params = {}
        if name:
            params["name"] = name
        if node_id:
            params["node_id"] = node_id
        return self._request("GET", "/api/v1/domains", params=params or None)

    def resolve_domain(self, name: str, node_id: Optional[str] = None) -> Optional[dict]:
        """Resolve a domain name to an API domain record.

        Uses name filter on GET /api/v1/domains. Returns the first match
        or None if no domain found.
        """
        domains = self.list_domains(name=name, node_id=node_id)
        if domains:
            return domains[0]
        return None

    def compare_configs(
        self,
        domain_ids: List[str],
        config_type: Optional[str] = None,
    ) -> dict:
        """Compare configs across domains.

        Args:
            domain_ids: List of domain UUIDs to compare
            config_type: Config file type (e.g. psappsrv.cfg)

        Returns:
            Comparison result from PSA-OPS
        """
        query_parts = [
            ("domain_ids", did) for did in domain_ids
        ]
        if config_type:
            query_parts.append(("config_type", config_type))
        qs = urllib.parse.urlencode(query_parts)
        return self._request("GET", f"/api/v1/configs/compare?{qs}")

    def get_domain_drift(
        self,
        domain_id: str,
        config_type: Optional[str] = None,
    ) -> dict:
        """Get drift details for a domain.

        Args:
            domain_id: Domain UUID
            config_type: Optional config file type filter
        """
        params = {}
        if config_type:
            params["config_type"] = config_type
        return self._request(
            "GET", f"/api/v1/domains/{domain_id}/drift", params=params or None
        )

    def update_domain(self, domain_id: str, **kwargs: Any) -> dict:
        """Update a domain via PATCH.

        Args:
            domain_id: UUID of the domain
            **kwargs: Fields to update (e.g. status="Running")
        """
        data = {k: v for k, v in kwargs.items() if v is not None}
        return self._request("PATCH", f"/api/v1/domains/{domain_id}", data=data)

    def get_drift_summary(self, domain_id: str) -> dict:
        """Get drift summary across all config types for a domain."""
        return self._request("GET", f"/api/v1/domains/{domain_id}/drift/summary")


class ApiError(Exception):
    """Error from PSA-OPS API."""

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
