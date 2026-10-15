"""
Ferramentas de rede: roda ping, arp e tracert do próprio sistema e lê as
saídas no Windows (em português ou inglês), no Linux e no macOS.

Por que usar os comandos do sistema em vez de sockets ICMP? No Windows, um
socket ICMP "cru" exige rodar como Administrador; o ping.exe já tem essa
permissão. Assim o HomeNOC roda como usuário comum e sem dependências.
"""

from __future__ import annotations

import ipaddress
import math
import os
import platform
import re
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

SISTEMA = platform.system()          # "Windows", "Linux" ou "Darwin"
WINDOWS = SISTEMA == "Windows"
MAX_HOSTS = 1022                     # varre no máximo uma /22

PORTAS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 139: "NetBIOS",
    443: "HTTPS", 445: "SMB (Windows)", 554: "RTSP (câmera)", 631: "IPP (impressora)",
    1883: "MQTT", 3389: "Área de Trabalho Remota", 5000: "UPnP/Web", 8008: "Chromecast",
    8009: "Chromecast", 8080: "HTTP alternativo", 8443: "HTTPS alternativo",
    9100: "Impressão RAW", 10050: "Zabbix agent", 62078: "iPhone/iPad",
}

NOMES_CONHECIDOS = {
    "8.8.8.8": "Google DNS", "8.8.4.4": "Google DNS 2", "1.1.1.1": "Cloudflare DNS",
    "1.0.0.1": "Cloudflare DNS 2", "9.9.9.9": "Quad9", "208.67.222.222": "OpenDNS",
}

IP_RE = r"(\d{1,3}(?:\.\d{1,3}){3})"
_LAT_RE = re.compile(r"(?:tempo|time)\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.I)
_MAC_RE = r"([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})"
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


# =====================================================================
# Execução de comandos
# =====================================================================

def run(cmd: list[str], timeout: float = 30) -> str:
    """Roda um comando e devolve a saída em texto (o Windows usa a página de código OEM)."""
    opcoes: dict = ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if WINDOWS
                    else {"env": {**os.environ, "LC_ALL": "C"}})
    try:
        saida = subprocess.run(cmd, capture_output=True, timeout=timeout, **opcoes).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for codificacao in (("oem", "cp850", "utf-8") if WINDOWS else ("utf-8",)):
        try:
            return saida.decode(codificacao)
        except (LookupError, UnicodeDecodeError):
            continue
    return saida.decode("utf-8", "replace")


# =====================================================================
# Leitura das saídas (testadas com textos reais do Windows pt-BR e en)
# =====================================================================

def _tem_ip(linha: str, ip: str) -> bool:
    """True se a linha contém exatamente esse IP (192.168.0.1 não casa com 192.168.0.10)."""
    return re.search(r"(?<![\d.])" + re.escape(ip) + r"(?![\d])", linha) is not None


def parse_ping(texto: str) -> tuple[bool, float | None, int | None]:
    """(respondeu, latência em ms, TTL).

    Só vale como resposta se houver "TTL=": o ping do Windows devolve código 0
    até para "Host de destino inacessível", que vem do roteador, não do alvo.
    """
    ttl = re.search(r"ttl[=:]\s*(\d+)", texto, re.I)
    if not ttl:
        return False, None, None
    lat = _LAT_RE.search(texto)
    return True, (float(lat.group(1).replace(",", ".")) if lat else None), int(ttl.group(1))


def parse_arp(texto: str) -> dict[str, str]:
    """IP -> MAC (aa:bb:cc:dd:ee:ff) a partir de 'arp -a' (Windows) ou 'ip neigh' (Linux)."""
    tabela = {}
    for linha in texto.splitlines():
        m = re.search(IP_RE + r"\s+.*?" + _MAC_RE, linha)
        if not m or re.search(r"FAILED|INCOMPLETE", linha):
            continue
        mac = m.group(2).replace("-", ":").lower()
        if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or mac.startswith("01:00:5e"):
            continue
        tabela[m.group(1)] = mac
    return tabela


def parse_tracert(texto: str) -> list[dict]:
    """Saltos do tracert/traceroute: [{'salto': 1, 'ip': '192.168.1.1', 'ms': 1.0}, ...]."""
    saltos = []
    for linha in texto.splitlines():
        m = re.match(r"^\s*(\d+)\s+(.*)$", linha)
        if not m:
            continue
        resto = m.group(2)
        ips = re.findall(IP_RE, resto)
        tempos = [float(t.replace(",", ".")) for t in re.findall(r"<?(\d+(?:[.,]\d+)?)\s*ms", resto)]
        saltos.append({"salto": int(m.group(1)), "ip": ips[-1] if ips else None,
                       "ms": min(tempos) if tempos else None})
    return saltos


def parse_route_print(texto: str, ip_local: str) -> str | None:
    """Gateway padrão no 'route print -4' do Windows (prefere a rota da placa com o IP local)."""
    candidatos = []
    for linha in texto.splitlines():
        m = re.match(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+" + IP_RE + r"\s+" + IP_RE + r"\s+(\d+)", linha)
        if m:
            candidatos.append((m.group(2) != ip_local, int(m.group(3)), m.group(1)))
    return sorted(candidatos)[0][2] if candidatos else None


def _blocos_ipconfig(texto: str) -> list[list[str]]:
    """Separa a saída do ipconfig em um bloco por adaptador."""
    blocos: list[list[str]] = []
    for linha in texto.splitlines():
        if linha.strip() and not linha[0].isspace():
            blocos.append([linha])
        elif blocos:
            blocos[-1].append(linha)
    return blocos


def parse_mascara_ipconfig(texto: str, ip_local: str) -> str | None:
    """Máscara de sub-rede do adaptador que tem o IP local (ipconfig em português ou inglês)."""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if "IPv4" in linha and _tem_ip(linha, ip_local):
            for prox in linhas[i + 1:i + 4]:
                if re.search(r"M.scara|Subnet Mask", prox, re.I):
                    m = re.search(IP_RE, prox)
                    return m.group(1) if m else None
    return None


def parse_mac_ipconfig(texto: str, ip_local: str) -> str | None:
    """MAC do adaptador que tem o IP local, no 'ipconfig /all'."""
    for bloco in _blocos_ipconfig(texto):
        if any("IPv4" in linha and _tem_ip(linha, ip_local) for linha in bloco):
            for linha in bloco:
                if re.search(r"Endere.o F.sico|Physical Address", linha, re.I):
                    m = re.search(_MAC_RE, linha)
                    if m:
                        return m.group(1).replace("-", ":").lower()
    return None


# =====================================================================
# Comandos
# =====================================================================

def comando_ping(ip: str, timeout_ms: int) -> list[str]:
    if WINDOWS:
        return ["ping", "-n", "1", "-w", str(int(timeout_ms)), ip]
    segundos = str(max(1, math.ceil(timeout_ms / 1000)))
    if SISTEMA == "Darwin":
        return ["ping", "-n", "-c", "1", "-t", segundos, ip]
    return ["ping", "-n", "-c", "1", "-W", segundos, ip]  # -n: sem DNS reverso (trava sem internet)


def ping(ip: str, timeout_ms: int = 1000) -> tuple[bool, float | None, int | None]:
    return parse_ping(run(comando_ping(ip, timeout_ms), timeout=timeout_ms / 1000 + 4))


def ping_tentativas(ip: str, tentativas: int = 2, timeout_ms: int = 1000,
                    dormir: Callable[[float], None] = time.sleep,
                    ping_fn: Callable = None) -> tuple[bool, float | None, int | None, int]:
    """Até N tentativas; a primeira resposta basta. Devolve (ok, ms, ttl, tentativas usadas)."""
    ping_fn = ping_fn or ping
    for n in range(1, tentativas + 1):
        ok, ms, ttl = ping_fn(ip, timeout_ms)
        if ok:
            return True, ms, ttl, n
        if n < tentativas:
            dormir(1.0)
    return False, None, None, tentativas


def ip_local() -> str:
    """IP da placa que sai para a internet (não envia pacote: UDP sem conexão real)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def rede_local() -> dict:
    """IP, máscara, gateway e MAC desta máquina, e a rede a varrer."""
    ip = ip_local()
    gateway = mascara = mac = None
    if WINDOWS:
        gateway = parse_route_print(run(["route", "print", "-4"]), ip)
        texto = run(["ipconfig", "/all"])
        mascara = parse_mascara_ipconfig(texto, ip)
        mac = parse_mac_ipconfig(texto, ip)
    elif SISTEMA == "Darwin":
        m = re.search(r"gateway:\s*" + IP_RE, run(["route", "-n", "get", "default"]))
        gateway = m.group(1) if m else None
    else:
        m = re.search(r"default via " + IP_RE, run(["ip", "-4", "route", "show", "default"]))
        gateway = m.group(1) if m else None
        m = re.search(r"^\d+:\s+(\S+)\s+inet\s+" + re.escape(ip) + r"/(\d+)",
                      run(["ip", "-4", "-o", "addr"]), re.M)
        if m:
            mascara = str(ipaddress.ip_network(f"0.0.0.0/{m.group(2)}").netmask)
            try:
                mac = Path(f"/sys/class/net/{m.group(1)}/address").read_text().strip().lower() or None
            except OSError:
                pass
    try:
        rede = ipaddress.ip_interface(f"{ip}/{mascara or '255.255.255.0'}").network
    except ValueError:
        rede = ipaddress.ip_interface(f"{ip}/24").network
    if rede.num_addresses - 2 > MAX_HOSTS:   # rede grande demais: só a /22 em volta do IP
        rede = ipaddress.ip_interface(f"{ip}/22").network
    return {"ip": ip, "gateway": gateway, "rede": str(rede), "mascara": str(rede.netmask),
            "mac": mac, "host": socket.gethostname()}


def tabela_arp() -> dict[str, str]:
    return parse_arp(run(["arp", "-a"]) if WINDOWS else run(["ip", "neigh"]))


def tracert(destino: str = "8.8.8.8") -> list[dict]:
    cmd = (["tracert", "-d", "-h", "10", "-w", "700", destino] if WINDOWS else
           ["traceroute", "-n", "-m", "10", "-w", "1", "-q", "1", destino])
    return parse_tracert(run(cmd, timeout=60))


def nome_dns(ip: str) -> str | None:
    try:
        nome = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return None
    return None if nome == ip else nome


def portas_abertas(ip: str, portas: tuple[int, ...] = tuple(PORTAS), timeout: float = 0.5) -> list[int]:
    abertas = []
    for porta in portas:
        try:
            with socket.create_connection((ip, porta), timeout=timeout):
                abertas.append(porta)
        except OSError:
            pass
    return abertas


# =====================================================================
# Interpretação
# =====================================================================

def palpite_so(ttl: int | None) -> str | None:
    if ttl is None:
        return None
    if ttl <= 64:
        return "Linux, Android, iOS, macOS ou embarcado (TTL inicial 64)"
    if ttl <= 128:
        return "Windows (TTL inicial 128)"
    return "Equipamento de rede: roteador, switch ou impressora (TTL inicial 255)"


def mac_aleatorio(mac: str | None) -> bool:
    """MAC 'localmente administrado' = endereço aleatório de privacidade (comum em celulares)."""
    try:
        return bool(mac) and int(mac.split(":")[0], 16) & 0b10 == 0b10
    except ValueError:
        return False


def eh_privado(ip: str | None) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private and not eh_cgnat(ip)
    except (ValueError, TypeError):
        return False


def eh_cgnat(ip: str | None) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10")
    except (ValueError, TypeError):
        return False


def host_valido(host: str) -> bool:
    """IP ou nome de host. Nunca começa com '-', então não vira opção do ping."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        if re.fullmatch(r"[\d.]+", host or ""):
            return False                    # só números e pontos, mas não é IP: erro de digitação
        return bool(_HOSTNAME_RE.match(host or ""))


def classificar(d: dict, gateway: str | None, eu: str | None) -> tuple[str, list[str]]:
    """Palpite do tipo de aparelho a partir das pistas coletadas, com o motivo."""
    portas = set(d.get("portas") or [])
    upnp = d.get("upnp") or {}
    texto = " ".join(filter(None, [d.get("fabricante"), upnp.get("fabricante"), upnp.get("modelo"),
                                   upnp.get("nome"), upnp.get("tipo"), d.get("nome_dns")])).lower()
    ttl = d.get("ttl")
    if eu and d.get("ip") == eu:
        return "este_pc", ["é este computador"]
    if gateway and d.get("ip") == gateway:
        return "roteador", ["é o gateway padrão da rede"]
    if upnp.get("tipo") in ("InternetGatewayDevice", "WANDevice"):
        return "roteador", ["anuncia-se como roteador via UPnP"]
    if portas & {9100, 631} or re.search(r"printer|epson|hp inc|brother|canon|lexmark", texto):
        return "impressora", ["porta de impressão aberta" if portas & {9100, 631} else "fabricante de impressoras"]
    if (portas & {8008, 8009} or upnp.get("tipo") == "MediaRenderer"
            or re.search(r"\btv\b|roku|chromecast|fire ?tv|webos|tizen|bravia|smarttv", texto)):
        motivo = "serviço de mídia (Chromecast ou DLNA)" if portas & {8008, 8009} or upnp else "nome de TV"
        return "tv", [motivo]
    if 554 in portas or re.search(r"camera|câmera|hikvision|intelbras|dahua|ezviz", texto):
        return "camera", ["porta RTSP (vídeo) aberta" if 554 in portas else "fabricante de câmeras"]
    if 62078 in portas or d.get("mac_aleatorio") or re.search(r"apple|samsung elec|xiaomi|motorola|oneplus", texto):
        motivo = ("porta de iPhone/iPad aberta" if 62078 in portas else
                  "MAC aleatório (privacidade de celular)" if d.get("mac_aleatorio") else "fabricante de celulares")
        return "celular", [motivo]
    if portas & {445, 139, 3389} or (ttl and 64 < ttl <= 128):
        return "computador", ["portas de compartilhamento do Windows" if portas & {445, 139, 3389}
                              else "TTL típico do Windows"]
    if 1883 in portas or re.search(r"espressif|tuya|sonoff|raspberry|shelly|amazon", texto):
        return "iot", ["porta MQTT aberta" if 1883 in portas else "fabricante de dispositivos IoT"]
    if 22 in portas:
        return "servidor", ["SSH aberto"]
    return "desconhecido", ["sem pistas suficientes"]
