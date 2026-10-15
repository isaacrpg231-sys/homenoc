#!/usr/bin/env python3
"""
UPnP do HomeNOC.

1. Descobre aparelhos que se anunciam por UPnP/SSDP (TVs, roteador, consoles)
   e lê o nome, o fabricante e o modelo de cada um.
2. Lê do roteador (UPnP IGD) os contadores de tráfego da internet da casa toda
   e as informações da conexão: IP público, tempo conectado e velocidade do link.

Também funciona sozinho, como "verificação externa" do Zabbix. Copie este
arquivo como upnp_wan.py para a pasta ExternalScripts do Zabbix:
    upnp_wan.py recebidos    total de bytes baixados   (gráfico de download)
    upnp_wan.py enviados     total de bytes enviados   (gráfico de upload)
    upnp_wan.py --testar     confere se o seu roteador suporta

Só usa a biblioteca padrão do Python 3.8+.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import struct
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HTTP_TIMEOUT_S = 3
SSDP_ESPERA_S = 2.0
# Endereço multicast padrão do SSDP. Os testes trocam por um endereço local.
SSDP_ADDR = os.environ.get("UPNP_SSDP_ADDR", "239.255.255.250:1900")
CACHE_FILE = os.environ.get("UPNP_CACHE_FILE",
                            os.path.join(tempfile.gettempdir(), "upnp_wan_cache.json"))
USER_AGENT = "HomeNOC-UPnP/1.0"

ALVOS_IGD = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1",
)
ACOES = {
    "recebidos": ("GetTotalBytesReceived", "NewTotalBytesReceived"),
    "enviados": ("GetTotalBytesSent", "NewTotalBytesSent"),
}
APELIDOS = {"download": "recebidos", "upload": "enviados"}
_ERROS_LEITURA = (OSError, ET.ParseError, ValueError)


class UPnPError(Exception):
    """Falha de descoberta ou de leitura, com mensagem pronta para o usuário."""


# ---------------------------------------------------------------------
# Descoberta (SSDP) e descrição dos aparelhos
# ---------------------------------------------------------------------

def gateway_padrao() -> str | None:
    """IP do gateway padrão no Linux (usado no modo Zabbix, que roda numa VM Linux)."""
    try:
        with open("/proc/net/route", encoding="ascii") as rotas:
            for linha in rotas.readlines()[1:]:
                campos = linha.split()
                if len(campos) > 3 and campos[1] == "00000000" and int(campos[3], 16) & 2:
                    return socket.inet_ntoa(struct.pack("<L", int(campos[2], 16)))
    except (OSError, ValueError):
        pass
    return None


def ssdp_buscar(alvos: tuple[str, ...], espera: float | None = None) -> list[tuple[str, str]]:
    """Pergunta na rede quem responde a cada alvo; devolve (ip de quem respondeu, URL de descrição)."""
    espera = SSDP_ESPERA_S if espera is None else espera
    host, porta = SSDP_ADDR.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    respostas: list[tuple[str, str]] = []
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.3)
        for alvo in alvos:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: {host}:{porta}\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {alvo}\r\n\r\n")
            sock.sendto(msg.encode("ascii"), (host, int(porta)))
        fim = time.monotonic() + espera
        while time.monotonic() < fim:
            try:
                dados, (ip, _) = sock.recvfrom(4096)
            except TimeoutError:
                continue
            for linha in dados.decode("utf-8", "replace").split("\r\n"):
                nome, _, valor = linha.partition(":")
                par = (ip, valor.strip())
                if nome.strip().lower() == "location" and valor.strip() and par not in respostas:
                    respostas.append(par)
    except OSError:
        pass
    finally:
        sock.close()
    return respostas


def _local(tag: str) -> str:
    """Nome da tag sem o namespace XML ({urn:...}friendlyName -> friendlyName)."""
    return tag.rsplit("}", 1)[-1]


def _filho(elemento: ET.Element | None, nome: str) -> str | None:
    if elemento is None:
        return None
    for filho in elemento:
        if _local(filho.tag) == nome and (filho.text or "").strip():
            return filho.text.strip()
    return None


def ler_descricao(location: str) -> dict | None:
    """Baixa o XML de descrição: nome, fabricante, modelo, tipo e os serviços com suas URLs."""
    if not location.lower().startswith(("http://", "https://")):
        return None
    req = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            raiz = ET.fromstring(r.read(300_000))
    except _ERROS_LEITURA:
        return None
    base = location
    for el in raiz.iter():
        if _local(el.tag) == "URLBase" and (el.text or "").strip():
            base = el.text.strip()
    dispositivo = next((e for e in raiz.iter() if _local(e.tag) == "device"), None)
    servicos = {}
    for el in raiz.iter():
        if _local(el.tag) == "service":
            tipo, controle = _filho(el, "serviceType"), _filho(el, "controlURL")
            if tipo and controle and tipo not in servicos:
                servicos[tipo] = urllib.parse.urljoin(base, controle)
    tipo_disp = _filho(dispositivo, "deviceType") or ""
    partes = tipo_disp.split(":")
    return {
        "location": location,
        "nome": _filho(dispositivo, "friendlyName"),
        "fabricante": _filho(dispositivo, "manufacturer"),
        "modelo": _filho(dispositivo, "modelName"),
        "tipo": partes[-2] if len(partes) >= 2 else None,
        "servicos": servicos,
    }


def descobrir_aparelhos(espera: float | None = None) -> dict[str, dict]:
    """IP -> {nome, fabricante, modelo, tipo} de todos que respondem ao UPnP."""
    if espera is None:
        espera = SSDP_ESPERA_S * 1.5        # aparelhos variados demoram mais que o roteador a responder
    por_ip: dict[str, list[str]] = {}
    for ip, location in ssdp_buscar(("ssdp:all",), espera):
        por_ip.setdefault(ip, []).append(location)
    resultado = {}
    for ip, locais in por_ip.items():
        melhor = None
        for location in sorted(set(locais)):
            info = ler_descricao(location)
            if not info:
                continue
            if melhor is None or (info.get("tipo") == "InternetGatewayDevice"):
                melhor = info
            if info.get("tipo") == "InternetGatewayDevice":
                break
        if melhor:
            resultado[ip] = {k: melhor[k] for k in ("nome", "fabricante", "modelo", "tipo")}
    return resultado


# ---------------------------------------------------------------------
# Roteador (IGD): contadores e informações da internet
# ---------------------------------------------------------------------

def _servico(info: dict, trecho: str) -> tuple[str, str] | None:
    for tipo, url in (info.get("servicos") or {}).items():
        if trecho in tipo:
            return tipo, url
    return None


def descobrir_roteador(gateway: str | None = None) -> dict:
    """Acha o roteador com contadores de tráfego. Se houver mais de um, prefere o gateway."""
    locais = [loc for _, loc in ssdp_buscar(ALVOS_IGD)]
    locais = list(dict.fromkeys(locais))
    if not locais:
        raise UPnPError("nenhum roteador respondeu ao UPnP. Ative o UPnP no roteador "
                        "(menus NAT, Avançado ou Rede) ou use SNMP.")
    locais.sort(key=lambda url: urllib.parse.urlparse(url).hostname != gateway)
    for location in locais:
        info = ler_descricao(location)
        if info and _servico(info, "WANCommonInterfaceConfig"):
            return info
    raise UPnPError("o roteador respondeu ao UPnP, mas não informa os contadores de tráfego "
                    "(serviço WANCommonInterfaceConfig ausente). Tente SNMP.")


def soap(url: str, tipo_servico: str, acao: str) -> dict[str, str]:
    """Chama uma ação UPnP sem argumentos e devolve os campos da resposta."""
    corpo = ('<?xml version="1.0"?>'
             '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
             's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
             f'<s:Body><u:{acao} xmlns:u="{tipo_servico}"></u:{acao}></s:Body></s:Envelope>')
    req = urllib.request.Request(
        url, data=corpo.encode("utf-8"),
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": f'"{tipo_servico}#{acao}"', "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
        raiz = ET.fromstring(r.read(100_000))
    return {_local(el.tag): (el.text or "").strip() for el in raiz.iter() if len(el) == 0}


def contador(info: dict, qual: str) -> int:
    acao, campo = ACOES[qual]
    servico = _servico(info, "WANCommonInterfaceConfig")
    if not servico:
        raise UPnPError("o roteador não informa os contadores de tráfego.")
    valor = soap(servico[1], servico[0], acao).get(campo, "")
    if not valor.isdigit():
        raise UPnPError(f"o roteador não devolveu {campo}.")
    return int(valor)


def info_wan(info: dict) -> dict:
    """IP público, estado e tempo da conexão, e velocidade do link, quando o roteador informa."""
    dados = {k: info.get(k) for k in ("nome", "fabricante", "modelo")}
    conexao = _servico(info, "WANIPConnection") or _servico(info, "WANPPPConnection")
    if conexao:
        try:
            resposta = soap(conexao[1], conexao[0], "GetExternalIPAddress")
            dados["ip_publico"] = resposta.get("NewExternalIPAddress") or None
        except _ERROS_LEITURA:
            pass
        try:
            st = soap(conexao[1], conexao[0], "GetStatusInfo")
            dados["conexao"] = st.get("NewConnectionStatus") or None
            dados["uptime_s"] = int(st.get("NewUptime") or 0) or None
        except _ERROS_LEITURA:
            pass
    comum = _servico(info, "WANCommonInterfaceConfig")
    if comum:
        try:
            lp = soap(comum[1], comum[0], "GetCommonLinkProperties")
            dados["link_down_bps"] = int(lp.get("NewLayer1DownstreamMaxBitRate") or 0) or None
            dados["link_up_bps"] = int(lp.get("NewLayer1UpstreamMaxBitRate") or 0) or None
            dados["link"] = lp.get("NewPhysicalLinkStatus") or None
        except _ERROS_LEITURA:
            pass
    ip = dados.get("ip_publico")
    try:
        endereco = ipaddress.ip_address(ip) if ip else None
    except ValueError:
        endereco = None
    dados["cgnat"] = bool(endereco and endereco in ipaddress.ip_network("100.64.0.0/10"))
    dados["nat_duplo"] = bool(endereco and endereco.is_private and not dados["cgnat"])
    return dados


class Roteador:
    """Lembra onde fica o roteador UPnP e o redescobre se ele mudar (reinício, outra porta)."""

    def __init__(self, gateway_fn=lambda: None) -> None:
        self.gateway_fn = gateway_fn
        self.info: dict | None = None

    def _ler(self, info: dict) -> tuple[int, int]:
        return contador(info, "recebidos"), contador(info, "enviados")

    def contadores(self) -> tuple[int, int]:
        if self.info is not None:
            try:
                return self._ler(self.info)
            except (*_ERROS_LEITURA, UPnPError):
                self.info = None
        self.info = descobrir_roteador(self.gateway_fn())
        try:
            return self._ler(self.info)
        except _ERROS_LEITURA as exc:
            self.info = None
            raise UPnPError(f"o roteador foi achado, mas a leitura falhou: {exc}") from None

    def informacoes(self) -> dict:
        if self.info is None:
            self.info = descobrir_roteador(self.gateway_fn())
        return info_wan(self.info)


# ---------------------------------------------------------------------
# Modo linha de comando (verificação externa do Zabbix)
# ---------------------------------------------------------------------

def _ler_cache() -> dict | None:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) and dados.get("servicos") else None
    except (OSError, ValueError):
        return None


def _salvar_cache(info: dict) -> None:
    """Guarda onde estão os contadores, para não refazer a descoberta a cada leitura."""
    tmp = f"{CACHE_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.replace(tmp, CACHE_FILE)
    except OSError:  # sem cache só fica um pouco mais lento
        try:
            os.remove(tmp)
        except OSError:
            pass


def ler_contador(qual: str) -> int:
    """Lê um contador usando o cache; se falhar, redescobre o roteador e tenta de novo."""
    info = _ler_cache()
    if info:
        try:
            return contador(info, qual)
        except (*_ERROS_LEITURA, UPnPError):
            pass
    info = descobrir_roteador(gateway_padrao())
    _salvar_cache(info)
    try:
        return contador(info, qual)
    except _ERROS_LEITURA as exc:
        raise UPnPError(f"falha ao ler o contador: {exc}") from None


def _taxa(bps: float) -> str:
    texto = f"{bps / 1e6:.2f} Mbps" if bps >= 1e5 else f"{bps / 1e3:.1f} kbps"
    return texto.replace(".", ",")


def _bytes(n: int) -> str:
    return f"{n / 1e9:.2f} GB".replace(".", ",")


def testar(amostra_s: float = 5.0) -> int:
    print("Procurando o roteador via UPnP...")
    try:
        info = descobrir_roteador(gateway_padrao())
    except UPnPError as exc:
        print(f"[ERRO] {exc}")
        return 1
    _salvar_cache(info)
    marca = " ".join(filter(None, [info.get("fabricante"), info.get("modelo")]))
    print(f"[OK] Roteador: {info.get('nome') or '?'}" + (f" ({marca})" if marca else ""))
    print(f"     Descrição: {info['location']}")
    try:
        primeiro = {k: contador(info, k) for k in ACOES}
        print(f"[OK] Contadores atuais: {_bytes(primeiro['recebidos'])} recebidos, "
              f"{_bytes(primeiro['enviados'])} enviados")
        print(f"     Medindo a velocidade por {amostra_s:g} segundos...")
        time.sleep(amostra_s)
        segundo = {k: contador(info, k) for k in ACOES}
    except (*_ERROS_LEITURA, UPnPError) as exc:
        print(f"[ERRO] O roteador foi achado, mas a leitura falhou: {exc}")
        return 1
    taxas = {k: (segundo[k] - primeiro[k]) * 8 / amostra_s for k in ACOES}
    if min(taxas.values()) < 0:
        print("[AVISO] Um contador diminuiu durante a medição (deu a volta ou o roteador "
              "reiniciou). Rode o teste de novo.")
    else:
        print(f"[OK] Download agora: {_taxa(taxas['recebidos'])} | Upload agora: {_taxa(taxas['enviados'])}")
    extras = info_wan(info)
    if extras.get("ip_publico"):
        nota = (" (CGNAT: a operadora divide o IP público)" if extras["cgnat"] else
                " (IP privado: há NAT duplo, outro roteador/ONT na frente)" if extras["nat_duplo"] else "")
        print(f"[OK] IP público informado pelo roteador: {extras['ip_publico']}{nota}")
    print("\nTudo certo: dá para usar este script no Zabbix (passo 5 do guia).")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    if argv[0] == "--testar":
        return testar()
    qual = APELIDOS.get(argv[0].lower(), argv[0].lower())
    if qual not in ACOES:
        print(f"parâmetro inválido: {argv[0]!r} (use recebidos ou enviados)", file=sys.stderr)
        return 2
    try:
        print(ler_contador(qual))
    except UPnPError as exc:
        print(f"upnp_wan: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
