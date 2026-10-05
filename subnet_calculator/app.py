from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ─── Helper Functions ───────────────────────────────────────────────

UINT32_MAX = 0xFFFFFFFF


def ip_str_to_int(ip_str):
    parts = ip_str.strip().split(".")
    if len(parts) != 4:
        raise ValueError("Invalid IPv4 format.")

    value = 0
    for part in parts:
        if not part.isdigit():
            raise ValueError("IPv4 octets must be numeric.")
        octet = int(part)
        if octet < 0 or octet > 255:
            raise ValueError("IPv4 octet out of range (0-255).")
        value = (value << 8) | octet
    return value


def int_to_ip(value):
    value = value & UINT32_MAX
    return ".".join(str((value >> shift) & 255) for shift in (24, 16, 8, 0))


def prefix_to_mask_int(prefix):
    if prefix < 0 or prefix > 32:
        raise ValueError("Prefix must be between 0 and 32.")
    if prefix == 0:
        return 0
    return (UINT32_MAX << (32 - prefix)) & UINT32_MAX


def parse_cidr(cidr):
    parts = cidr.strip().split("/")
    if len(parts) != 2:
        raise ValueError("CIDR must be in a.b.c.d/prefix format.")

    ip_raw = parts[0].strip()
    prefix_raw = parts[1].strip()
    if not prefix_raw.isdigit():
        raise ValueError("CIDR prefix must be numeric.")

    prefix = int(prefix_raw)
    ip_int = ip_str_to_int(ip_raw)
    mask_int = prefix_to_mask_int(prefix)
    network_int = ip_int & mask_int
    broadcast_int = network_int | (UINT32_MAX ^ mask_int)

    return {
        "input_ip": ip_raw,
        "input_ip_int": ip_int,
        "prefix": prefix,
        "mask_int": mask_int,
        "network_int": network_int,
        "broadcast_int": broadcast_int,
    }


def ip_to_binary(ip_str):
    ip_int = ip_str_to_int(ip_str)
    return ".".join(format((ip_int >> shift) & 255, "08b") for shift in (24, 16, 8, 0))


def range_overlaps(a_start, a_end, b_start, b_end):
    return not (a_end < b_start or b_end < a_start)


def get_ip_class(ip_str):
    try:
        first_octet = int(ip_str.split(".")[0])
        if 1 <= first_octet <= 126:
            return "A"
        if 128 <= first_octet <= 191:
            return "B"
        if 192 <= first_octet <= 223:
            return "C"
        if 224 <= first_octet <= 239:
            return "D (Multicast)"
        if 240 <= first_octet <= 255:
            return "E (Reserved)"
        return "Unknown"
    except Exception:
        return "Unknown"


def is_private(network_start, network_end):
    private_ranges = [
        parse_cidr("10.0.0.0/8"),
        parse_cidr("172.16.0.0/12"),
        parse_cidr("192.168.0.0/16"),
    ]
    for block in private_ranges:
        if range_overlaps(
            network_start,
            network_end,
            block["network_int"],
            block["broadcast_int"],
        ):
            return True
    return False


def calculate_subnet(cidr):
    try:
        details = parse_cidr(cidr)
        ip = details["input_ip"]
        prefix = details["prefix"]
        network_int = details["network_int"]
        broadcast_int = details["broadcast_int"]
        mask_int = details["mask_int"]

        total_hosts = 1 << (32 - prefix)
        usable_hosts = max(total_hosts - 2, 0)

        mask = int_to_ip(mask_int)
        wildcard = int_to_ip(UINT32_MAX ^ mask_int)
        network_addr = int_to_ip(network_int)
        broadcast = int_to_ip(broadcast_int)

        if total_hosts <= 2:
            first_host = "N/A"
            last_host = "N/A"
        else:
            first_host = int_to_ip(network_int + 1)
            last_host = int_to_ip(broadcast_int - 1)

        ip_class = get_ip_class(network_addr)
        private = is_private(network_int, broadcast_int)

        binary_ip = ip_to_binary(ip)
        binary_mask = ip_to_binary(mask)
        binary_network = ip_to_binary(network_addr)

        return {
            "success": True,
            "input_ip": ip,
            "prefix": prefix,
            "network_address": network_addr,
            "broadcast": broadcast,
            "subnet_mask": mask,
            "wildcard_mask": wildcard,
            "first_host": first_host,
            "last_host": last_host,
            "total_hosts": total_hosts,
            "usable_hosts": usable_hosts,
            "ip_class": ip_class,
            "is_private": private,
            "binary_ip": binary_ip,
            "binary_mask": binary_mask,
            "binary_network": binary_network,
            "cidr": f"{network_addr}/{prefix}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def split_subnet(cidr, n):
    try:
        if n < 2:
            return {"success": False, "error": "Split count must be at least 2."}

        parent = parse_cidr(cidr)
        parent_prefix = parent["prefix"]
        parent_network = parent["network_int"]
        parent_broadcast = parent["broadcast_int"]

        bits_needed = 0
        subnet_count = 1
        while subnet_count < n:
            bits_needed += 1
            subnet_count *= 2

        new_prefix = parent_prefix + bits_needed
        if new_prefix > 32:
            return {"success": False, "error": "Not enough address space to split into that many subnets."}

        subnet_size = 1 << (32 - new_prefix)
        result = []
        for i in range(n):
            subnet_network = parent_network + (i * subnet_size)
            subnet_broadcast = subnet_network + subnet_size - 1
            if subnet_broadcast > parent_broadcast:
                break

            result.append(
                {
                    "cidr": f"{int_to_ip(subnet_network)}/{new_prefix}",
                    "network": int_to_ip(subnet_network),
                    "broadcast": int_to_ip(subnet_broadcast),
                    "mask": int_to_ip(prefix_to_mask_int(new_prefix)),
                    "first_host": int_to_ip(subnet_network + 1) if subnet_size > 2 else "N/A",
                    "last_host": int_to_ip(subnet_broadcast - 1) if subnet_size > 2 else "N/A",
                    "usable_hosts": max(subnet_size - 2, 0),
                }
            )
        return {"success": True, "subnets": result, "parent": cidr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vlsm_calculate(network_cidr, requirements):
    """VLSM: allocate subnets from a pool in descending size order."""
    try:
        pool = parse_cidr(network_cidr)
        pool_start = pool["network_int"]
        pool_end = pool["broadcast_int"]
        requirements_sorted = sorted(requirements, key=lambda x: x["hosts"], reverse=True)

        allocated = []
        remaining = [(pool_start, pool_end)]

        for req in requirements_sorted:
            needed = req["hosts"] + 2  # network + broadcast
            if needed < 1:
                needed = 1

            block_size = 1
            while block_size < needed:
                block_size *= 2

            temp = block_size
            bits = 0
            while temp > 1:
                temp //= 2
                bits += 1
            prefix = 32 - bits

            chosen_index = -1
            chosen_start = None
            chosen_end = None
            for i, (start, end) in enumerate(remaining):
                aligned_start = ((start + block_size - 1) // block_size) * block_size
                candidate_end = aligned_start + block_size - 1
                if aligned_start <= end and candidate_end <= end:
                    chosen_index = i
                    chosen_start = aligned_start
                    chosen_end = candidate_end
                    break

            if chosen_index == -1:
                return {
                    "success": False,
                    "error": f"Not enough space for '{req['name']}' needing {req['hosts']} hosts.",
                }

            old_start, old_end = remaining.pop(chosen_index)
            if old_start < chosen_start:
                remaining.append((old_start, chosen_start - 1))
            if chosen_end < old_end:
                remaining.append((chosen_end + 1, old_end))
            remaining.sort(key=lambda r: r[0])

            allocated.append(
                {
                    "name": req["name"],
                    "required_hosts": req["hosts"],
                    "cidr": f"{int_to_ip(chosen_start)}/{prefix}",
                    "network": int_to_ip(chosen_start),
                    "broadcast": int_to_ip(chosen_end),
                    "mask": int_to_ip(prefix_to_mask_int(prefix)),
                    "first_host": int_to_ip(chosen_start + 1) if block_size > 2 else "N/A",
                    "last_host": int_to_ip(chosen_end - 1) if block_size > 2 else "N/A",
                    "usable_hosts": max(block_size - 2, 0),
                    "prefix": prefix,
                }
            )

        return {"success": True, "allocations": allocated, "pool": network_cidr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_overlap(cidrs):
    try:
        networks = []
        for c in cidrs:
            c = c.strip()
            if c:
                parsed = parse_cidr(c)
                networks.append((c, parsed["network_int"], parsed["broadcast_int"]))

        overlaps = []
        for i in range(len(networks)):
            for j in range(i + 1, len(networks)):
                if range_overlaps(networks[i][1], networks[i][2], networks[j][1], networks[j][2]):
                    overlaps.append({"a": networks[i][0], "b": networks[j][0]})

        return {"success": True, "overlaps": overlaps, "count": len(overlaps)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ip_in_subnet(ip, cidr):
    try:
        addr = ip_str_to_int(ip)
        net = parse_cidr(cidr)
        inside = net["network_int"] <= addr <= net["broadcast_int"]
        return {"success": True, "result": inside, "ip": ip, "cidr": cidr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def batch_calculate(cidrs):
    results = []
    for c in cidrs:
        c = c.strip()
        if c:
            results.append(calculate_subnet(c))
    return {"success": True, "results": results}


def supernet_calculate(cidrs):
    try:
        parsed = []
        for c in cidrs:
            c = c.strip()
            if c:
                block = parse_cidr(c)
                parsed.append((block["network_int"], block["broadcast_int"]))

        if len(parsed) < 2:
            return {"success": False, "error": "Need at least 2 networks to supernet."}

        parsed.sort(key=lambda x: x[0])
        merged = [parsed[0]]
        for start, end in parsed[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end + 1:
                if end > last_end:
                    merged[-1] = (last_start, end)
            else:
                merged.append((start, end))

        collapsed = []
        for start, end in merged:
            current = start
            while current <= end:
                size = 1
                while current % (size * 2) == 0 and (size * 2) <= (end - current + 1):
                    size *= 2

                bits = 0
                temp = size
                while temp > 1:
                    bits += 1
                    temp //= 2
                prefix = 32 - bits

                collapsed.append((current, prefix, size))
                current += size

        result = []
        for network_int, prefix, size in collapsed:
            result.append(
                {
                    "cidr": f"{int_to_ip(network_int)}/{prefix}",
                    "network": int_to_ip(network_int),
                    "mask": int_to_ip(prefix_to_mask_int(prefix)),
                    "total_hosts": size,
                }
            )
        return {"success": True, "supernets": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/subnet", methods=["POST"])
def api_subnet():
    data = request.json
    return jsonify(calculate_subnet(data.get("cidr", "")))


@app.route("/api/split", methods=["POST"])
def api_split():
    data = request.json
    return jsonify(split_subnet(data.get("cidr", ""), int(data.get("n", 2))))


@app.route("/api/vlsm", methods=["POST"])
def api_vlsm():
    data = request.json
    return jsonify(vlsm_calculate(data.get("network", ""), data.get("requirements", [])))


@app.route("/api/overlap", methods=["POST"])
def api_overlap():
    data = request.json
    return jsonify(check_overlap(data.get("cidrs", [])))


@app.route("/api/ip-in-subnet", methods=["POST"])
def api_ip_in_subnet():
    data = request.json
    return jsonify(ip_in_subnet(data.get("ip", ""), data.get("cidr", "")))


@app.route("/api/batch", methods=["POST"])
def api_batch():
    data = request.json
    return jsonify(batch_calculate(data.get("cidrs", [])))


@app.route("/api/supernet", methods=["POST"])
def api_supernet():
    data = request.json
    return jsonify(supernet_calculate(data.get("cidrs", [])))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
from flask import Flask, render_template, request, jsonify
import ipaddress
import json

app = Flask(__name__)

# ─── Helper Functions ───────────────────────────────────────────────

def get_ip_class(ip_str):
    try:
        first_octet = int(ip_str.split('.')[0])
        if 1 <= first_octet <= 126:
            return 'A'
        elif 128 <= first_octet <= 191:
            return 'B'
        elif 192 <= first_octet <= 223:
            return 'C'
        elif 224 <= first_octet <= 239:
            return 'D (Multicast)'
        elif 240 <= first_octet <= 255:
            return 'E (Reserved)'
        return 'Unknown'
    except:
        return 'Unknown'

def is_private(network):
    private_ranges = [
        ipaddress.IPv4Network('10.0.0.0/8'),
        ipaddress.IPv4Network('172.16.0.0/12'),
        ipaddress.IPv4Network('192.168.0.0/16'),
    ]
    return any(network.overlaps(r) for r in private_ranges)

def ip_to_binary(ip_str):
    parts = ip_str.split('.')
    return '.'.join(format(int(p), '08b') for p in parts)

def calculate_subnet(cidr):
    try:
        network = ipaddress.IPv4Network(cidr, strict=False)
        ip = cidr.split('/')[0]
        prefix = network.prefixlen

        total_hosts = network.num_addresses
        usable_hosts = max(total_hosts - 2, 0)

        mask = str(network.netmask)
        wildcard = str(network.hostmask)
        network_addr = str(network.network_address)
        broadcast = str(network.broadcast_address)

        hosts = list(network.hosts())
        first_host = str(hosts[0]) if hosts else 'N/A'
        last_host = str(hosts[-1]) if hosts else 'N/A'

        ip_class = get_ip_class(network_addr)
        private = is_private(network)

        binary_ip = ip_to_binary(ip)
        binary_mask = ip_to_binary(mask)
        binary_network = ip_to_binary(network_addr)

        return {
            'success': True,
            'input_ip': ip,
            'prefix': prefix,
            'network_address': network_addr,
            'broadcast': broadcast,
            'subnet_mask': mask,
            'wildcard_mask': wildcard,
            'first_host': first_host,
            'last_host': last_host,
            'total_hosts': total_hosts,
            'usable_hosts': usable_hosts,
            'ip_class': ip_class,
            'is_private': private,
            'binary_ip': binary_ip,
            'binary_mask': binary_mask,
            'binary_network': binary_network,
            'cidr': str(network),
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def split_subnet(cidr, n):
    try:
        network = ipaddress.IPv4Network(cidr, strict=False)
        new_prefix = network.prefixlen
        # Find smallest prefix that gives >= n subnets
        import math
        bits_needed = math.ceil(math.log2(n)) if n > 1 else 1
        new_prefix = network.prefixlen + bits_needed
        if new_prefix > 32:
            return {'success': False, 'error': 'Not enough address space to split into that many subnets.'}

        subnets = list(network.subnets(new_prefix=new_prefix))[:n]
        result = []
        for s in subnets:
            hosts = list(s.hosts())
            result.append({
                'cidr': str(s),
                'network': str(s.network_address),
                'broadcast': str(s.broadcast_address),
                'mask': str(s.netmask),
                'first_host': str(hosts[0]) if hosts else 'N/A',
                'last_host': str(hosts[-1]) if hosts else 'N/A',
                'usable_hosts': max(s.num_addresses - 2, 0),
            })
        return {'success': True, 'subnets': result, 'parent': cidr}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def vlsm_calculate(network_cidr, requirements):
    """VLSM: allocate subnets from a pool in descending size order."""
    try:
        pool = ipaddress.IPv4Network(network_cidr, strict=False)
        requirements_sorted = sorted(requirements, key=lambda x: x['hosts'], reverse=True)

        allocated = []
        remaining = [pool]

        for req in requirements_sorted:
            needed = req['hosts'] + 2  # network + broadcast
            # find smallest prefix
            prefix = 32
            while (2 ** (32 - prefix)) < needed and prefix > 0:
                prefix -= 1

            found = None
            for i, block in enumerate(remaining):
                if block.prefixlen <= prefix:
                    sub = list(block.subnets(new_prefix=prefix))[0]
                    found = (i, block, sub)
                    break

            if not found:
                return {'success': False, 'error': f"Not enough space for '{req['name']}' needing {req['hosts']} hosts."}

            idx, parent, subnet = found
            remaining.pop(idx)
            # Add back the leftover space
            leftovers = list(parent.address_exclude(subnet))
            remaining = sorted(remaining + leftovers, key=lambda x: x.prefixlen)

            hosts = list(subnet.hosts())
            allocated.append({
                'name': req['name'],
                'required_hosts': req['hosts'],
                'cidr': str(subnet),
                'network': str(subnet.network_address),
                'broadcast': str(subnet.broadcast_address),
                'mask': str(subnet.netmask),
                'first_host': str(hosts[0]) if hosts else 'N/A',
                'last_host': str(hosts[-1]) if hosts else 'N/A',
                'usable_hosts': max(subnet.num_addresses - 2, 0),
                'prefix': subnet.prefixlen,
            })

        return {'success': True, 'allocations': allocated, 'pool': network_cidr}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def check_overlap(cidrs):
    try:
        networks = []
        for c in cidrs:
            c = c.strip()
            if c:
                networks.append((c, ipaddress.IPv4Network(c, strict=False)))

        overlaps = []
        for i in range(len(networks)):
            for j in range(i + 1, len(networks)):
                if networks[i][1].overlaps(networks[j][1]):
                    overlaps.append({
                        'a': networks[i][0],
                        'b': networks[j][0],
                    })

        return {'success': True, 'overlaps': overlaps, 'count': len(overlaps)}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def ip_in_subnet(ip, cidr):
    try:
        addr = ipaddress.IPv4Address(ip)
        net = ipaddress.IPv4Network(cidr, strict=False)
        return {'success': True, 'result': addr in net, 'ip': ip, 'cidr': cidr}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def batch_calculate(cidrs):
    results = []
    for c in cidrs:
        c = c.strip()
        if c:
            results.append(calculate_subnet(c))
    return {'success': True, 'results': results}


def supernet_calculate(cidrs):
    try:
        networks = [ipaddress.IPv4Network(c.strip(), strict=False) for c in cidrs if c.strip()]
        if len(networks) < 2:
            return {'success': False, 'error': 'Need at least 2 networks to supernet.'}
        collapsed = list(ipaddress.collapse_addresses(networks))
        result = []
        for n in collapsed:
            result.append({
                'cidr': str(n),
                'network': str(n.network_address),
                'mask': str(n.netmask),
                'total_hosts': n.num_addresses,
            })
        return {'success': True, 'supernets': result}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ─── Routes ───────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/subnet', methods=['POST'])
def api_subnet():
    data = request.json
    return jsonify(calculate_subnet(data.get('cidr', '')))

@app.route('/api/split', methods=['POST'])
def api_split():
    data = request.json
    return jsonify(split_subnet(data.get('cidr', ''), int(data.get('n', 2))))

@app.route('/api/vlsm', methods=['POST'])
def api_vlsm():
    data = request.json
    return jsonify(vlsm_calculate(data.get('network', ''), data.get('requirements', [])))

@app.route('/api/overlap', methods=['POST'])
def api_overlap():
    data = request.json
    return jsonify(check_overlap(data.get('cidrs', [])))

@app.route('/api/ip-in-subnet', methods=['POST'])
def api_ip_in_subnet():
    data = request.json
    return jsonify(ip_in_subnet(data.get('ip', ''), data.get('cidr', '')))

@app.route('/api/batch', methods=['POST'])
def api_batch():
    data = request.json
    return jsonify(batch_calculate(data.get('cidrs', [])))

@app.route('/api/supernet', methods=['POST'])
def api_supernet():
    data = request.json
    return jsonify(supernet_calculate(data.get('cidrs', [])))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
