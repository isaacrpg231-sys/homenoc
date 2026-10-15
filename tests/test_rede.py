"""Leitura das saídas do ping, arp, tracert, route e ipconfig (Windows pt-BR/en e Linux) e classificação."""

import shutil
import unittest

import apoio  # noqa: F401  (ajusta o sys.path)

from homenoc import rede

ARP_WIN = """
Interface: 192.168.0.10 --- 0x12
  Endereço IP           Endereço físico       Tipo
  192.168.0.1           a4-2b-b0-11-22-33     dinâmico
  192.168.0.21          f4-7b-09-12-34-56     dinâmico
  192.168.0.255         ff-ff-ff-ff-ff-ff     estático
  224.0.0.22            01-00-5e-00-00-16     estático
"""
ARP_LINUX = """192.168.0.1 dev eth0 lladdr a4:2b:b0:11:22:33 REACHABLE
192.168.0.99 dev eth0 FAILED
"""
TRACERT_WIN = """
Rastreando a rota para 8.8.8.8 com no máximo 10 saltos

  1    <1 ms    <1 ms    <1 ms  192.168.0.1
  2     2 ms     1 ms     2 ms  192.168.1.1
  3     *        *        *     Esgotado o tempo limite do pedido.
  4     9 ms     8 ms     9 ms  100.64.12.1
  5    12 ms    11 ms    12 ms  8.8.8.8

Rastreamento concluído.
"""
ROUTE_WIN = """
IPv4 Tabela de rota
===========================================================================
Rotas ativas:
Endereço de rede             Máscara     Ender. gateway     Interface  Custo
          0.0.0.0          0.0.0.0      192.168.56.1     192.168.56.10    281
          0.0.0.0          0.0.0.0      192.168.0.1     192.168.0.10     25
        127.0.0.0        255.0.0.0         No vínculo         127.0.0.1    331
"""
IPCONFIG_ALL = """
Configuração de IP do Windows

   Nome do host. . . . . . . . . . . . . . . . : NOTEBOOK-ISAAC

Adaptador Ethernet Ethernet 2:

   Descrição . . . . . . . . . . . . . . . . . : VirtualBox Host-Only Ethernet Adapter
   Endereço Físico . . . . . . . . . . . . . . : 0A-00-27-00-00-05
   Endereço IPv4. . . . . . . . . . . . . . .  : 192.168.0.100(Preferencial)
   Máscara de Sub-rede . . . . . . . . . . . . : 255.255.255.0

Adaptador de Rede sem Fio Wi-Fi:

   Descrição . . . . . . . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX201 160MHz
   Endereço Físico . . . . . . . . . . . . . . : 3C-52-82-AA-BB-01
   Endereço IPv4. . . . . . . . . . . . . . .  : 192.168.0.10(Preferencial)
   Máscara de Sub-rede . . . . . . . . . . . . : 255.255.255.0
   Gateway Padrão. . . . . . . . . . . . . . . : 192.168.0.1
"""
IPCONFIG_EN = """
Wireless LAN adapter Wi-Fi:

   Physical Address. . . . . . . . . : 3C-52-82-AA-BB-01
   IPv4 Address. . . . . . . . . . . : 10.0.0.5(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.252.0
"""


class Leitores(unittest.TestCase):
    def test_ping_windows_ptbr_e_en(self):
        self.assertEqual(rede.parse_ping("Resposta de 192.168.0.1: bytes=32 tempo<1ms TTL=64"), (True, 1.0, 64))
        self.assertEqual(rede.parse_ping("Resposta de 8.8.8.8: bytes=32 tempo=14ms TTL=117"), (True, 14.0, 117))
        self.assertEqual(rede.parse_ping("Reply from 1.1.1.1: bytes=32 time=9ms TTL=58"), (True, 9.0, 58))

    def test_ping_windows_host_inacessivel_nao_conta(self):
        # A pegadinha clássica: o Windows devolve código 0 nesse caso.
        self.assertEqual(rede.parse_ping("Resposta de 192.168.0.10: Host de destino inacessível."),
                         (False, None, None))
        self.assertEqual(rede.parse_ping("Esgotado o tempo limite do pedido."), (False, None, None))
        self.assertEqual(rede.parse_ping("Resposta de 10.0.0.1: TTL expirado em trânsito."), (False, None, None))

    def test_ping_linux(self):
        self.assertEqual(rede.parse_ping("64 bytes from 192.168.0.1: icmp_seq=1 ttl=64 time=0.48 ms"),
                         (True, 0.48, 64))
        self.assertEqual(rede.parse_ping("1 packets transmitted, 0 received, 100% packet loss"),
                         (False, None, None))

    def test_arp(self):
        self.assertEqual(rede.parse_arp(ARP_WIN), {"192.168.0.1": "a4:2b:b0:11:22:33",
                                                   "192.168.0.21": "f4:7b:09:12:34:56"})
        self.assertEqual(rede.parse_arp(ARP_LINUX), {"192.168.0.1": "a4:2b:b0:11:22:33"})

    def test_tracert(self):
        saltos = rede.parse_tracert(TRACERT_WIN)
        self.assertEqual([s["ip"] for s in saltos], ["192.168.0.1", "192.168.1.1", None, "100.64.12.1", "8.8.8.8"])
        self.assertEqual((saltos[0]["ms"], saltos[4]["ms"]), (1.0, 11.0))

    def test_gateway_mascara_e_mac(self):
        self.assertEqual(rede.parse_route_print(ROUTE_WIN, "192.168.0.10"), "192.168.0.1")
        self.assertEqual(rede.parse_mascara_ipconfig(IPCONFIG_ALL, "192.168.0.10"), "255.255.255.0")
        self.assertEqual(rede.parse_mac_ipconfig(IPCONFIG_ALL, "192.168.0.10"), "3c:52:82:aa:bb:01")
        self.assertEqual(rede.parse_mac_ipconfig(IPCONFIG_ALL, "192.168.0.100"), "0a:00:27:00:00:05")
        self.assertEqual(rede.parse_mac_ipconfig(IPCONFIG_EN, "10.0.0.5"), "3c:52:82:aa:bb:01")
        self.assertEqual(rede.parse_mascara_ipconfig(IPCONFIG_EN, "10.0.0.5"), "255.255.252.0")

    def test_ip_parecido_nao_confunde(self):
        # 192.168.0.1 não pode casar com a linha do 192.168.0.10 nem do 192.168.0.100
        self.assertIsNone(rede.parse_mac_ipconfig(IPCONFIG_ALL, "192.168.0.1"))

    def test_comandos_por_sistema(self):
        original = rede.WINDOWS, rede.SISTEMA
        try:
            rede.WINDOWS, rede.SISTEMA = True, "Windows"
            self.assertEqual(rede.comando_ping("8.8.8.8", 2000), ["ping", "-n", "1", "-w", "2000", "8.8.8.8"])
            rede.WINDOWS, rede.SISTEMA = False, "Linux"
            self.assertEqual(rede.comando_ping("8.8.8.8", 1500), ["ping", "-n", "-c", "1", "-W", "2", "8.8.8.8"])
            rede.SISTEMA = "Darwin"
            self.assertEqual(rede.comando_ping("8.8.8.8", 1000), ["ping", "-n", "-c", "1", "-t", "1", "8.8.8.8"])
        finally:
            rede.WINDOWS, rede.SISTEMA = original

    def test_tentativas_param_na_primeira_resposta(self):
        respostas = iter([(False, None, None), (True, 3.2, 64)])
        pausas = []
        ok, ms, ttl, n = rede.ping_tentativas("192.168.0.1", 3, dormir=pausas.append,
                                             ping_fn=lambda ip, t: next(respostas))
        self.assertEqual((ok, ms, ttl, n, pausas), (True, 3.2, 64, 2, [1.0]))

    @unittest.skipUnless(shutil.which("ping"), "sem o comando ping")
    def test_ping_de_verdade_no_proprio_computador(self):
        # Roda o ping real do sistema (no CI roda no Windows e no Linux) e confere a leitura.
        ok, ms, ttl = rede.ping("127.0.0.1", 1000)
        if not ok:
            self.skipTest("ping em 127.0.0.1 bloqueado neste ambiente")
        self.assertIsNotNone(ttl)


class Interpretacao(unittest.TestCase):
    def tipo(self, **d):
        base = {"ip": "192.168.0.50", "portas": [], "ttl": None, "fabricante": None, "nome_dns": None, "upnp": None}
        return rede.classificar({**base, **d}, "192.168.0.1", "192.168.0.10")[0]

    def test_tipos(self):
        self.assertEqual(self.tipo(ip="192.168.0.1"), "roteador")
        self.assertEqual(self.tipo(ip="192.168.0.10"), "este_pc")
        self.assertEqual(self.tipo(upnp={"tipo": "InternetGatewayDevice"}), "roteador")
        self.assertEqual(self.tipo(portas=[631, 9100]), "impressora")
        self.assertEqual(self.tipo(portas=[8008, 8009]), "tv")
        self.assertEqual(self.tipo(upnp={"tipo": "MediaRenderer", "nome": "[LG] webOS TV"}), "tv")
        self.assertEqual(self.tipo(portas=[554]), "camera")
        self.assertEqual(self.tipo(portas=[62078]), "celular")
        self.assertEqual(self.tipo(mac_aleatorio=True), "celular")
        self.assertEqual(self.tipo(portas=[445], ttl=128), "computador")
        self.assertEqual(self.tipo(ttl=128), "computador")
        self.assertEqual(self.tipo(fabricante="Espressif"), "iot")
        self.assertEqual(self.tipo(portas=[22], ttl=64), "servidor")
        self.assertEqual(self.tipo(), "desconhecido")

    def test_palavra_tv_nao_casa_dentro_de_outra(self):
        self.assertEqual(self.tipo(nome_dns="tvbox.lan"), "desconhecido")

    def test_mac_aleatorio_so_e_enderecos(self):
        self.assertTrue(rede.mac_aleatorio("da:1f:3e:77:10:2c"))
        self.assertFalse(rede.mac_aleatorio("a4:2b:b0:11:22:33"))
        self.assertFalse(rede.mac_aleatorio(None))
        self.assertIn("Windows", rede.palpite_so(128))
        self.assertIn("rede", rede.palpite_so(255))
        self.assertTrue(rede.eh_cgnat("100.64.12.1"))
        self.assertFalse(rede.eh_cgnat("187.100.33.9"))
        self.assertTrue(rede.eh_privado("192.168.1.1"))
        self.assertFalse(rede.eh_privado("100.64.0.1"))

    def test_host_valido(self):
        for bom in ("8.8.8.8", "1.1.1.1", "dns.google", "roteador.lan"):
            self.assertTrue(rede.host_valido(bom), bom)
        for ruim in ("999.1.1.1", "192.168.1", "-f", "", "a b"):
            self.assertFalse(rede.host_valido(ruim), ruim)


if __name__ == "__main__":
    unittest.main(verbosity=2)
