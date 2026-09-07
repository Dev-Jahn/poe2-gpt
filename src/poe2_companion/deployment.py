"""Standard-library-only renderer for a small, isolated friend deployment.

Input is Docker Compose's resolved JSON plus operator-owned membership records.
This module never reads builds or credentials and is not exposed through MCP.
"""
from copy import deepcopy
import re

MEMBER_ID = re.compile(r"[a-z][a-z0-9-]{0,23}")
EMAIL = re.compile(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}")
PRIVATE_VOLUMES = {"engine-socket", "private-builds", "build-projections"}


def validate_members(members, owner_email):
    if not isinstance(members, list) or len(members) > 64:
        raise ValueError("Invalid membership list")
    ids, emails, ports = {"owner"}, {owner_email.casefold()}, {18080, 18081}
    active = 0
    for member in members:
        if not isinstance(member, dict) or set(member) != {"id", "email", "port", "enabled"}:
            raise ValueError("Invalid membership record")
        identity, email, port = member["id"], member["email"], member["port"]
        if (not isinstance(identity, str) or not MEMBER_ID.fullmatch(identity) or identity in ids
                or not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email)
                or email.casefold() in emails or type(port) is not int or not 18082 <= port <= 18145
                or port in ports or type(member["enabled"]) is not bool):
            raise ValueError("Membership IDs, emails and ports must be valid and unique; retired IDs remain reserved")
        ids.add(identity)
        emails.add(email.casefold())
        ports.add(port)
        active += member["enabled"]
    if active > 2:
        raise ValueError("This deployment supports one owner and two active friends")


def member_services(identity, engine):
    names = ["poe2-companion"] + (["pob-engine", "pob-import"] if engine else [])
    return [name + "-" + identity for name in names]


def render_member_stack(base, members):
    owner = base["services"]["poe2-companion"]
    validate_members(members, owner["environment"]["POE2_CF_OWNER_EMAIL"])
    stack = deepcopy(base)
    engine = "pob-engine" in base["services"]
    names = ["poe2-companion"] + (["pob-engine", "pob-import"] if engine else [])
    for member in members:
        if not member["enabled"]:
            continue
        identity = member["id"]
        for name in names:
            service = deepcopy(base["services"][name])
            # Both members use the same immutable image, with distinct processes.
            service.pop("build", None)
            for volume in service.get("volumes", []):
                if volume["type"] == "volume" and volume["source"] in PRIVATE_VOLUMES:
                    volume["source"] += "-" + identity
            if "depends_on" in service:
                service["depends_on"] = {key + "-" + identity: value for key, value in service["depends_on"].items()}
            if name == "poe2-companion":
                service["environment"]["POE2_CF_OWNER_EMAIL"] = member["email"].casefold()
                service["command"] += ["--mcp-path", f"/u/{identity}/mcp"]
                service["ports"] = [{"target": 8000, "published": str(member["port"]),
                                     "host_ip": "127.0.0.1", "protocol": "tcp"}]
            stack["services"][name + "-" + identity] = service
        for name in PRIVATE_VOLUMES.intersection(base.get("volumes", {})):
            entry = deepcopy(base["volumes"][name] or {})
            if "name" in entry:
                entry["name"] += "-" + identity
            stack.setdefault("volumes", {})[name + "-" + identity] = entry
    return stack
