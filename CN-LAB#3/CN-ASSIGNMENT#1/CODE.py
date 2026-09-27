import socket
import struct
import random
import sys


def build_dns_query(domain_name: str, query_type: int = 1) -> tuple[bytes, int]:
    transaction_id = random.randint(0, 65535)
    flags = 0x0100

    qdcount = 1
    ancount = 0
    nscount = 0
    arcount = 0

    header = struct.pack(
        "!HHHHHH",
        transaction_id,
        flags,
        qdcount,
        ancount,
        nscount,
        arcount,
    )

    qname = encode_domain_name(domain_name)
    qtype = struct.pack("!H", query_type)
    qclass = struct.pack("!H", 1)

    question = qname + qtype + qclass

    return header + question, transaction_id


def encode_domain_name(domain_name: str) -> bytes:
    encoded = b""
    for label in domain_name.strip(".").split("."):
        label_bytes = label.encode("ascii")
        if len(label_bytes) > 63:
            raise ValueError(f"DNS label too long: {label}")
        encoded += struct.pack("B", len(label_bytes)) + label_bytes
    encoded += b"\x00"
    return encoded


def decode_domain_name(packet: bytes, offset: int) -> tuple[str, int]:
    labels = []
    original_offset = None
    pos = offset

    while True:
        length_byte = packet[pos]

        if (length_byte & 0xC0) == 0xC0:
            if original_offset is None:
                original_offset = pos + 2
            pointer = struct.unpack("!H", packet[pos:pos + 2])[0]
            pos = pointer & 0x3FFF
            continue

        if length_byte == 0:
            pos += 1
            break

        pos += 1
        label = packet[pos:pos + length_byte].decode("ascii", errors="replace")
        labels.append(label)
        pos += length_byte

    end_offset = original_offset if original_offset is not None else pos
    return ".".join(labels), end_offset


def parse_dns_response(packet: bytes, expected_txn_id: int) -> dict:
    if len(packet) < 12:
        raise ValueError("Response too short to contain a valid DNS header")

    (txn_id, flags, qdcount, ancount, nscount, arcount) = struct.unpack(
        "!HHHHHH", packet[:12]
    )

    qr = (flags >> 15) & 0x1
    opcode = (flags >> 11) & 0xF
    aa = (flags >> 10) & 0x1
    tc = (flags >> 9) & 0x1
    rd = (flags >> 8) & 0x1
    ra = (flags >> 7) & 0x1
    rcode = flags & 0xF

    rcode_meanings = {
        0: "NOERROR",
        1: "FORMERR",
        2: "SERVFAIL",
        3: "NXDOMAIN",
        4: "NOTIMP",
        5: "REFUSED",
    }
    rcode_text = rcode_meanings.get(rcode, f"UNKNOWN({rcode})")

    result = {
        "transaction_id": txn_id,
        "transaction_id_matches": (txn_id == expected_txn_id),
        "qr": qr,
        "opcode": opcode,
        "authoritative": bool(aa),
        "truncated": bool(tc),
        "recursion_desired": bool(rd),
        "recursion_available": bool(ra),
        "rcode": rcode,
        "rcode_text": rcode_text,
        "qdcount": qdcount,
        "ancount": ancount,
        "question": None,
        "answers": [],
    }

    offset = 12

    if qdcount >= 1:
        qname, offset = decode_domain_name(packet, offset)
        qtype, qclass = struct.unpack("!HH", packet[offset:offset + 4])
        offset += 4
        result["question"] = {"name": qname, "qtype": qtype, "qclass": qclass}

    for _ in range(ancount):
        name, offset = decode_domain_name(packet, offset)

        rtype, rclass, ttl, rdlength = struct.unpack(
            "!HHIH", packet[offset:offset + 10]
        )
        offset += 10

        rdata_raw = packet[offset:offset + rdlength]

        answer = {
            "name": name,
            "type": rtype,
            "class": rclass,
            "ttl": ttl,
            "rdlength": rdlength,
        }

        if rtype == 1 and rdlength == 4:
            answer["ip_address"] = socket.inet_ntoa(rdata_raw)
        elif rtype == 5:
            cname, _ = decode_domain_name(packet, offset)
            answer["cname"] = cname
        else:
            answer["ip_address"] = None

        result["answers"].append(answer)
        offset += rdlength

    return result


def query_dns_server(domain_name: str, dns_server_ip: str, timeout: float = 4.0):
    query_packet, txn_id = build_dns_query(domain_name, query_type=1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    try:
        sock.sendto(query_packet, (dns_server_ip, 53))
        response_packet, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    return parse_dns_response(response_packet, txn_id)


def print_response(domain_name: str, dns_server_ip: str, response: dict):
    print("-" * 60)
    print(f"Query Name       : {domain_name}")
    print(f"DNS Server Used  : {dns_server_ip}")
    print(f"Transaction ID   : {response['transaction_id']} "
          f"(matches request: {response['transaction_id_matches']})")
    print(f"Query Type       : A (IPv4 address)")
    print(f"Response Status  : {response['rcode_text']}")
    print(f"Flags            : AA={response['authoritative']} "
          f"TC={response['truncated']} RD={response['recursion_desired']} "
          f"RA={response['recursion_available']}")
    print(f"Answer Count     : {response['ancount']}")

    if response["rcode_text"] == "NXDOMAIN":
        print("Result           : Domain does not exist (NXDOMAIN).")
        return

    if not response["answers"]:
        print("Result           : No answer records returned (query may need "
              "chasing a CNAME or server returned none).")
        return

    for i, ans in enumerate(response["answers"], start=1):
        print(f"  Answer #{i}:")
        print(f"    Name        : {ans['name']}")
        print(f"    TTL         : {ans['ttl']} seconds")
        if ans.get("ip_address"):
            print(f"    Resolved IP : {ans['ip_address']}")
        elif ans.get("cname"):
            print(f"    CNAME       : {ans['cname']}")
        else:
            print(f"    Type        : {ans['type']} (not an A/CNAME record)")


def is_probably_valid_domain(domain: str) -> bool:
    domain = domain.strip()
    if not domain or len(domain) > 253:
        return False
    if domain.startswith(".") or domain.endswith("-"):
        return False
    labels = domain.strip(".").split(".")
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
    return True


def main():
    print("=" * 60)
    print(" DNS Query Resolution Tool (raw UDP sockets, manual parsing)")
    print("=" * 60)

    dns_server_ip = input(
        "Enter the DNS server IP to query (e.g. 8.8.8.8): "
    ).strip()

    if not dns_server_ip:
        print("No DNS server IP provided. Exiting.")
        sys.exit(1)

    while True:
        domain_name = input(
            "\nEnter a domain name to resolve (or 'quit' to exit): "
        ).strip()

        if domain_name.lower() in ("quit", "exit", "q"):
            print("Exiting. Goodbye!")
            break

        if not is_probably_valid_domain(domain_name):
            print(f"'{domain_name}' does not look like a valid domain name. "
                  f"Please try again (e.g. www.example.com).")
            continue

        try:
            response = query_dns_server(domain_name, dns_server_ip)
            print_response(domain_name, dns_server_ip, response)

        except socket.timeout:
            print(f"Request timed out: no response received from "
                  f"{dns_server_ip} within the timeout period.")
        except socket.gaierror as e:
            print(f"Network/address error: {e}")
        except ValueError as e:
            print(f"Failed to build/parse DNS message: {e}")
        except Exception as e:
            print(f"Unexpected error while processing '{domain_name}': {e}")


if __name__ == "__main__":
    main()