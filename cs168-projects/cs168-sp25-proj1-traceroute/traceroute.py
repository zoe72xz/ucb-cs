import util
import struct

# Your program should send TTLs in the range [1, TRACEROUTE_MAX_TTL] inclusive.
# Technically IPv4 supports TTLs up to 255, but in practice this is excessive.
# Most traceroute implementations cap at approximately 30.  The unit tests
# assume you don't change this number.
TRACEROUTE_MAX_TTL = 30

# Cisco seems to have standardized on UDP ports [33434, 33464] for traceroute.
# While not a formal standard, it appears that some routers on the internet
# will only respond with time exceeeded ICMP messages to UDP packets send to
# those ports.  Ultimately, you can choose whatever port you like, but that
# range seems to give more interesting results.
TRACEROUTE_PORT_NUMBER = 33434  # Cisco traceroute port number.

# Sometimes packets on the internet get dropped.  PROBE_ATTEMPT_COUNT is the
# maximum number of times your traceroute function should attempt to probe a
# single router before giving up and moving on.
PROBE_ATTEMPT_COUNT = 3

class IPv4:
    # Each member below is a field from the IPv4 packet header.  They are
    # listed below in the order they appear in the packet.  All fields should
    # be stored in host byte order.
    #
    # You should only modify the __init__() method of this class.
    version: int
    header_len: int  # Note length in bytes, not the value in the packet.
    tos: int         # Also called DSCP and ECN bits (i.e. on wikipedia).
    length: int      # Total length of the packet.
    id: int
    flags: int
    frag_offset: int
    ttl: int
    proto: int
    cksum: int
    src: str
    dst: str

    def __init__(self, buffer: bytes):
        if len(buffer) < 20:
            raise ValueError("IPv4 header too short")
        unpacked = struct.unpack("!BBHHHBBH4s4s", buffer[:20])

        self.version = unpacked[0] >> 4
        self.header_len = (unpacked[0] & 0x0F) * 4
        self.tos = unpacked[1]
        self.length = unpacked[2]
        self.id = unpacked[3]
        self.flags = (unpacked[4] >> 13) & 0x07
        self.frag_offset = unpacked[4] & 0x1FFF
        self.ttl = unpacked[5]
        self.proto = unpacked[6]
        self.cksum = unpacked[7]
        self.src = util.inet_ntoa(unpacked[8])
        self.dst = util.inet_ntoa(unpacked[9])
        

    def __str__(self) -> str:
        return f"IPv{self.version} (tos 0x{self.tos:x}, ttl {self.ttl}, " + \
            f"id {self.id}, flags 0x{self.flags:x}, " + \
            f"ofsset {self.frag_offset}, " + \
            f"proto {self.proto}, header_len {self.header_len}, " + \
            f"len {self.length}, cksum 0x{self.cksum:x}) " + \
            f"{self.src} > {self.dst}"


class ICMP:
    # Each member below is a field from the ICMP header.  They are listed below
    # in the order they appear in the packet.  All fields should be stored in
    # host byte order.
    #
    # You should only modify the __init__() function of this class.
    type: int
    code: int
    cksum: int

    def __init__(self, buffer: bytes):
        if len(buffer) < 8:
            raise ValueError("ICMP header too short")
        unpacked = struct.unpack("!BBH", buffer[:4])
        self.type = unpacked[0]
        self.code = unpacked[1]
        self.cksum = unpacked[2]

    def __str__(self) -> str:
        return f"ICMP (type {self.type}, code {self.code}, " + \
            f"cksum 0x{self.cksum:x})"


class UDP:
    # Each member below is a field from the UDP header.  They are listed below
    # in the order they appear in the packet.  All fields should be stored in
    # host byte order.
    #
    # You should only modify the __init__() function of this class.
    src_port: int
    dst_port: int
    len: int
    cksum: int

    def __init__(self, buffer: bytes):
        if len(buffer) < 8:
            raise ValueError("UDP header too short")
        
        unpacked = struct.unpack("!HHHH", buffer[:8])
        self.src_port = unpacked[0]
        self.dst_port = unpacked[1]
        self.len = unpacked[2]
        self.cksum = unpacked[3]

    def __str__(self) -> str:
        return f"UDP (src_port {self.src_port}, dst_port {self.dst_port}, " + \
            f"len {self.len}, cksum 0x{self.cksum:x})"

# TODO feel free to add helper functions if you'd like

def traceroute(sendsock: util.Socket, recvsock: util.Socket, ip: str) \
        -> list[list[str]]:
    """ Run traceroute and returns the discovered path.

    Calls util.print_result() on the result of each TTL's probes to show
    progress.

    Arguments:
    sendsock -- This is a UDP socket you will use to send traceroute probes.
    recvsock -- This is the socket on which you will receive ICMP responses.
    ip -- This is the IP address of the end host you will be tracerouting.

    Returns:
    A list of lists representing the routers discovered for each ttl that was
    probed.  The ith list contains all of the routers found with TTL probe of
    i+1.   The routers discovered in the ith list can be in any order.  If no
    routers were found, the ith list can be empty.  If `ip` is discovered, it
    should be included as the final element in the list.
    """

    discovered_paths = []
    seen_packets = set()
    
    for ttl in range(1, TRACEROUTE_MAX_TTL + 1):
        sendsock.set_ttl(ttl)
        routers = set()
        responses_received = 0
        
        for _ in range(PROBE_ATTEMPT_COUNT):
            probe_payload = f"TracerouteProbe-{ttl}".encode()
            sendsock.sendto(probe_payload, (ip, TRACEROUTE_PORT_NUMBER))
        
        while recvsock.recv_select():
            try:
                buf, address = recvsock.recvfrom()
                if len(buf) < 28:
                    continue  
                
                ipv4_header = IPv4(buf[:20])
                if ipv4_header.proto != 1:
                    continue  
                
                header_offset = ipv4_header.header_len
                icmp_packet = ICMP(buf[header_offset:])

                if icmp_packet.type not in {11, 3} or (icmp_packet.type == 11 and icmp_packet.code != 0):
                    continue  
                
                if len(buf) < header_offset + 28:
                    continue  
                embedded_ip = IPv4(buf[header_offset + 8:])

                if embedded_ip.dst != ip:
                    continue  
                
                packet_id = (embedded_ip.ttl, address[0], icmp_packet.type, icmp_packet.code)

                if packet_id in seen_packets:
                    continue  
                seen_packets.add(packet_id)
                
                if embedded_ip.ttl != ttl:
                    continue
                
                routers.add(address[0])
                responses_received += 1

                if responses_received >= PROBE_ATTEMPT_COUNT:
                    break

                if address[0] == ip:
                    discovered_paths.append([ip])
                    util.print_result([ip], ttl)
                    return discovered_paths
                
            except ValueError:
                continue  

        discovered_paths.append(list(routers))
        util.print_result(list(routers), ttl)

    return discovered_paths


if __name__ == '__main__':
    args = util.parse_args()
    ip_addr = util.gethostbyname(args.host)
    print(f"traceroute to {args.host} ({ip_addr})")
    traceroute(util.Socket.make_udp(), util.Socket.make_icmp(), ip_addr)
