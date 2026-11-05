# -*- coding: utf-8 -*-
"""Lightweight Local Interface Binding Proxy (Python Standard Library).

Binds outbound client connections to a specific local IPv4 network adapter,
enabling multi-homed process routing (e.g. LAN vs USB Tethering HP) in Chrome.

Usage:
    python local_interface_proxy.py --bind-ip 192.168.42.88 --port 8001
"""
import argparse
import select
import socket
import struct
import sys
import threading

BUFFER_SIZE = 65536


def forward_tunnel(src: socket.socket, dst: socket.socket):
    """Bidirectional pipe between client and destination socket."""
    sockets = [src, dst]
    try:
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional or not readable:
                break
            for s in readable:
                other = dst if s is src else src
                data = s.recv(BUFFER_SIZE)
                if not data:
                    return
                other.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def handle_client(client_sock: socket.socket, bind_ip: str, if_index: int = None):
    try:
        req_line = b""
        while b"\r\n" not in req_line:
            chunk = client_sock.recv(1)
            if not chunk:
                client_sock.close()
                return
            req_line += chunk

        first_line = req_line.decode("latin1", errors="replace").strip()
        parts = first_line.split()
        if len(parts) < 2:
            client_sock.close()
            return

        method, target = parts[0], parts[1]

        # Read remainder of HTTP headers
        headers = req_line
        while b"\r\n\r\n" not in headers:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            headers += chunk

        if method.upper() == "CONNECT":
            # HTTPS tunnel: host:port
            if ":" in target:
                host, port_str = target.split(":", 1)
                port = int(port_str)
            else:
                host = target
                port = 443

            out_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            out_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if if_index:
                out_sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", if_index))
            elif bind_ip and bind_ip != "0.0.0.0":
                out_sock.bind((bind_ip, 0))
            out_sock.connect((host, port))

            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            forward_tunnel(client_sock, out_sock)
        else:
            # Plain HTTP request
            from urllib.parse import urlparse
            p = urlparse(target)
            host = p.hostname or target
            port = p.port or 80

            out_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            out_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if if_index:
                out_sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", if_index))
            elif bind_ip and bind_ip != "0.0.0.0":
                out_sock.bind((bind_ip, 0))
            out_sock.connect((host, port))

            # Send the original request
            out_sock.sendall(headers)
            forward_tunnel(client_sock, out_sock)

    except Exception:
        try:
            client_sock.close()
        except Exception:
            pass


def run_proxy(bind_ip: str, listen_port: int, listen_host: str = "127.0.0.1", if_index: int = None):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((listen_host, listen_port))
    server.listen(128)
    print(f"[+] Proxy listening on http://{listen_host}:{listen_port} -> Routing outbound via bind_ip={bind_ip} (if_index={if_index})")
    sys.stdout.flush()

    try:
        while True:
            client_sock, _ = server.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, bind_ip, if_index), daemon=True)
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Interface Binding Proxy")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="Local IPv4 address of network interface to route through")
    parser.add_argument("--if-index", type=int, default=None, help="Windows Network Interface Index (e.g. 23 for HP)")
    parser.add_argument("--port", type=int, default=8001, help="Local port to listen on (default: 8001)")
    parser.add_argument("--host", default="127.0.0.1", help="Local host to listen on (default: 127.0.0.1)")
    args = parser.parse_args()

    run_proxy(bind_ip=args.bind_ip, listen_port=args.port, listen_host=args.host, if_index=args.if_index)
