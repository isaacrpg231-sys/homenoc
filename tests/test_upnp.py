"""UPnP contra um roteador simulado: descoberta, contadores, informações da internet e modo Zabbix."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from apoio import pasta_temporaria

from homenoc import upnp

SCRIPT = Path(upnp.__file__)
TMP = pasta_temporaria()


class RoteadorFalso:
    """Responde à descrição UPnP (XML) e às ações SOAP como um roteador doméstico."""

    def __init__(self, ip="127.0.0.1", contadores=True, nome="Roteador Teste", ip_publico="187.100.33.9"):
        self.ip, self.contadores, self.nome, self.ip_publico = ip, contadores, nome, ip_publico
        self.recebidos, self.enviados = 1_000_000, 250_000
        self.buscas = 0
        self.caminho_controle = "/ctl/CommonIfCfg"
        roteador = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/rootDesc.xml":
                    self.send_error(404)
                    return
                comum = (f"""<service>
                  <serviceType>urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1</serviceType>
                  <controlURL>{roteador.caminho_controle}</controlURL></service>""" if roteador.contadores else "")
                self._xml(f"""<?xml version="1.0"?>
                <root xmlns="urn:schemas-upnp-org:device-1-0">
                  <device>
                    <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
                    <friendlyName>{roteador.nome}</friendlyName>
                    <manufacturer>ACME</manufacturer><modelName>AX-1500</modelName>
                    <deviceList><device>
                      <deviceType>urn:schemas-upnp-org:device:WANDevice:1</deviceType>
                      <serviceList>{comum}</serviceList>
                      <deviceList><device>
                        <deviceType>urn:schemas-upnp-org:device:WANConnectionDevice:1</deviceType>
                        <serviceList><service>
                          <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
                          <controlURL>/ctl/IPConn</controlURL>
                        </service></serviceList>
                      </device></deviceList>
                    </device></deviceList>
                  </device>
                </root>""")

            def do_POST(self):
                corpo = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                acao = self.headers.get("SOAPAction", "").strip('"').split("#")[-1]
                assert acao in corpo
                campos = {
                    "GetTotalBytesReceived": {"NewTotalBytesReceived": roteador.recebidos},
                    "GetTotalBytesSent": {"NewTotalBytesSent": roteador.enviados},
                    "GetCommonLinkProperties": {"NewWANAccessType": "Ethernet",
                                                "NewLayer1UpstreamMaxBitRate": 150_000_000,
                                                "NewLayer1DownstreamMaxBitRate": 300_000_000,
                                                "NewPhysicalLinkStatus": "Up"},
                    "GetExternalIPAddress": {"NewExternalIPAddress": roteador.ip_publico},
                    "GetStatusInfo": {"NewConnectionStatus": "Connected", "NewLastConnectionError": "ERROR_NONE",
                                      "NewUptime": 93784},
                }
                caminhos_validos = {roteador.caminho_controle, "/ctl/IPConn"}
                if self.path not in caminhos_validos or acao not in campos:
                    self.send_error(500)
                    return
                itens = "".join(f"<{k}>{v}</{k}>" for k, v in campos[acao].items())
                self._xml(f"""<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
                <s:Body><u:{acao}Response xmlns:u="urn:x">{itens}</u:{acao}Response></s:Body></s:Envelope>""")

            def _xml(self, texto):
                dados = texto.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *args):
                pass

        self.http = HTTPServer((ip, 0), Handler)
        self.location = f"http://{ip}:{self.http.server_port}/rootDesc.xml"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def responder(self, sock, endereco):
        self.buscas += 1
        sock.sendto(("HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\n"
                     f"LOCATION: {self.location}\r\nSERVER: Linux UPnP/1.0\r\n\r\n").encode(), endereco)

    def fechar(self):
        self.http.shutdown()
        self.http.server_close()


class SSDPFalso:
    """Recebe o M-SEARCH em unicast (no lugar do multicast) e faz cada roteador responder."""

    def __init__(self, roteadores):
        self.roteadores = roteadores
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.endereco = f"127.0.0.1:{self.sock.getsockname()[1]}"
        self.rodando = True
        threading.Thread(target=self._laco, daemon=True).start()

    def _laco(self):
        while self.rodando:
            try:
                dados, origem = self.sock.recvfrom(2048)
            except OSError:
                continue
            if dados.startswith(b"M-SEARCH") and (b"InternetGatewayDevice:1" in dados or b"ssdp:all" in dados):
                for r in self.roteadores:
                    r.responder(self.sock, origem)

    def fechar(self):
        self.rodando = False
        self.sock.close()


class UPnPTests(unittest.TestCase):
    def setUp(self):
        self.roteador = RoteadorFalso()
        self.ssdp = SSDPFalso([self.roteador])
        self.cache = TMP / f"cache_{self._testMethodName}.json"
        for nome, valor in (("SSDP_ADDR", self.ssdp.endereco), ("SSDP_ESPERA_S", 0.5),
                            ("CACHE_FILE", str(self.cache))):
            p = mock.patch.object(upnp, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.ssdp.fechar()
        self.roteador.fechar()

    def test_descobre_o_roteador_e_os_servicos(self):
        info = upnp.descobrir_roteador()
        self.assertEqual((info["nome"], info["modelo"], info["tipo"]), ("Roteador Teste", "AX-1500",
                                                                       "InternetGatewayDevice"))
        base = f"http://127.0.0.1:{self.roteador.http.server_port}"
        self.assertEqual(info["servicos"]["urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1"],
                         f"{base}/ctl/CommonIfCfg")
        self.assertEqual(info["servicos"]["urn:schemas-upnp-org:service:WANIPConnection:1"], f"{base}/ctl/IPConn")

    def test_le_contadores_e_lembra_do_roteador(self):
        r = upnp.Roteador()
        self.assertEqual(r.contadores(), (1_000_000, 250_000))
        self.roteador.recebidos = 3_000_000
        self.assertEqual(r.contadores(), (3_000_000, 250_000))
        self.assertEqual(self.roteador.buscas, 1)            # a 2ª leitura não refaz a descoberta

    def test_redescobre_se_o_roteador_mudou(self):
        r = upnp.Roteador()
        r.contadores()
        self.roteador.caminho_controle = "/novo/caminho"     # ex.: o roteador reiniciou
        self.roteador.recebidos = 5_000_000
        self.assertEqual(r.contadores()[0], 5_000_000)
        self.assertEqual(self.roteador.buscas, 2)

    def test_roteador_sem_contadores(self):
        self.roteador.contadores = False
        with self.assertRaises(upnp.UPnPError) as ctx:
            upnp.Roteador().contadores()
        self.assertIn("WANCommonInterfaceConfig", str(ctx.exception))

    def test_ninguem_responde(self):
        self.ssdp.roteadores = []
        with self.assertRaises(upnp.UPnPError) as ctx:
            upnp.Roteador().contadores()
        self.assertIn("Ative o UPnP", str(ctx.exception))

    def test_prefere_o_gateway_quando_ha_dois_roteadores(self):
        outro = RoteadorFalso(ip="127.0.0.2", nome="Roteador Principal")
        try:
            self.ssdp.roteadores = [self.roteador, outro]    # o principal responde por último
            self.assertEqual(upnp.descobrir_roteador("127.0.0.2")["nome"], "Roteador Principal")
        finally:
            outro.fechar()

    def test_informacoes_da_internet(self):
        info = upnp.Roteador().informacoes()
        self.assertEqual(info["ip_publico"], "187.100.33.9")
        self.assertEqual((info["conexao"], info["uptime_s"]), ("Connected", 93784))
        self.assertEqual((info["link_down_bps"], info["link_up_bps"], info["link"]), (300_000_000, 150_000_000, "Up"))
        self.assertFalse(info["cgnat"])
        self.assertFalse(info["nat_duplo"])

    def test_detecta_cgnat_e_nat_duplo(self):
        self.roteador.ip_publico = "100.64.12.1"
        self.assertTrue(upnp.Roteador().informacoes()["cgnat"])
        self.roteador.ip_publico = "192.168.1.1"
        info = upnp.Roteador().informacoes()
        self.assertTrue(info["nat_duplo"])
        self.assertFalse(info["cgnat"])

    def test_descobre_aparelhos_para_o_mapa(self):
        aparelhos = upnp.descobrir_aparelhos()
        self.assertEqual(aparelhos["127.0.0.1"], {"nome": "Roteador Teste", "fabricante": "ACME",
                                                  "modelo": "AX-1500", "tipo": "InternetGatewayDevice"})

    def test_modo_teste_mostra_velocidade_e_ip_publico(self):
        original = upnp.contador
        chamadas = {"n": 0}

        def crescendo(info, qual):
            chamadas["n"] += 1
            if chamadas["n"] > 2:                             # 2ª medição: +10 MB baixados, +1 MB enviados
                self.roteador.recebidos, self.roteador.enviados = 11_000_000, 1_250_000
            return original(info, qual)

        saida = io.StringIO()
        with mock.patch.object(upnp, "contador", side_effect=crescendo), \
             mock.patch.object(upnp.time, "sleep"), redirect_stdout(saida):
            codigo = upnp.testar(amostra_s=5)
        texto = saida.getvalue()
        self.assertEqual(codigo, 0)
        self.assertIn("Roteador: Roteador Teste (ACME AX-1500)", texto)
        self.assertIn("Download agora: 16,00 Mbps", texto)
        self.assertIn("Upload agora: 1,60 Mbps", texto)
        self.assertIn("IP público informado pelo roteador: 187.100.33.9", texto)
        self.assertIn("passo 5 do guia", texto)

    def test_parametros_invalidos(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(upnp.main([]), 2)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as erro:
            self.assertEqual(upnp.main(["xyz"]), 2)
        self.assertIn("recebidos ou enviados", erro.getvalue())

    def _rodar_como_zabbix(self, *args, cache):
        env = {**os.environ, "UPNP_SSDP_ADDR": self.ssdp.endereco, "UPNP_CACHE_FILE": str(cache),
               "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                              env=env, timeout=30)

    def test_como_o_zabbix_chama(self):
        # O Zabbix roda o script com o parâmetro e lê só a saída.
        r = self._rodar_como_zabbix("download", cache=self.cache)
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr), (0, "1000000", ""))
        self.assertTrue(self.cache.exists())

    def test_erro_vira_mensagem_legivel_no_zabbix(self):
        self.ssdp.roteadores = []
        r = self._rodar_como_zabbix("recebidos", cache=TMP / "vazio.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("upnp_wan: nenhum roteador respondeu", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
