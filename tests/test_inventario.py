"""Inventário: aparelho novo, IP que muda, quem sai e volta, roteador já monitorado."""

import unittest

from apoio import Relogio, config_e_banco

from homenoc.descoberta import Inventario, Varredura, nome_exibicao

REDE = {"ip": "192.168.0.10", "gateway": "192.168.0.1", "rede": "192.168.0.0/24", "mac": "3c:52:82:aa:bb:01",
        "host": "NOTEBOOK"}


def host(mac=None, ms=2.0, ttl=64, nome=None, portas=None, ping=True):
    return {"ms": ms if ping else None, "ttl": ttl if ping else None, "responde_ping": ping, "mac": mac,
            "nome_dns": nome, "portas": portas}


class FabricantesFalsos:
    def nome(self, mac):
        return {"a4:2b:b0": "TP-LINK", "f4:7b:09": "LG Electronics"}.get((mac or "")[:8])


class InventarioTests(unittest.TestCase):
    def setUp(self):
        self.config, self.banco = config_e_banco()
        self.relogio = Relogio()
        self.inv = Inventario(self.banco, FabricantesFalsos(), self.relogio)

    def varrer(self, hosts, upnp=None, minutos=5):
        self.relogio.avancar(minutos)
        return self.inv.aplicar(Varredura(REDE, hosts, upnp=upnp or {}))

    def eventos(self):
        return [(e["tipo"], e["titulo"]) for e in reversed(self.banco.eventos(100))]

    def base(self):
        return {"192.168.0.1": host("a4:2b:b0:11:22:33", 1.1, nome="roteador.lan", portas=[53, 80]),
                "192.168.0.10": host("3c:52:82:aa:bb:01", 0.0, 128),
                "192.168.0.21": host("f4:7b:09:12:34:56", 4.8, portas=[8008, 8009])}

    def test_primeira_varredura(self):
        r = self.varrer(self.base(), upnp={"192.168.0.21": {"nome": "[LG] webOS TV", "tipo": "MediaRenderer"}})
        self.assertTrue(r["primeira"])
        self.assertEqual((r["total"], r["online"], len(r["novos"])), (3, 3, 3))
        roteador = self.banco.dispositivo("mac:a4:2b:b0:11:22:33")
        self.assertEqual((roteador["tipo"], roteador["fabricante"]), ("roteador", "TP-LINK"))
        self.assertTrue(roteador["alertar"])                       # o roteador já começa monitorado
        trans = self.banco.estado("monitor.transicoes")
        self.assertEqual(trans["dispositivo:mac:a4:2b:b0:11:22:33"]["status"], "online")
        tv = self.banco.dispositivo("mac:f4:7b:09:12:34:56")
        self.assertEqual((tv["tipo"], nome_exibicao(tv)), ("tv", "[LG] webOS TV"))
        self.assertEqual(self.banco.dispositivo("mac:3c:52:82:aa:bb:01")["tipo"], "este_pc")
        self.assertEqual(self.eventos(), [("sistema", "Primeira varredura: 3 aparelhos encontrados")])

    def test_aparelho_novo_gera_evento(self):
        self.varrer(self.base())
        hosts = {**self.base(), "192.168.0.42": host("da:1f:3e:77:10:2c", 18, portas=[62078])}
        r = self.varrer(hosts)
        self.assertEqual([d["id"] for d in r["novos"]], ["mac:da:1f:3e:77:10:2c"])
        self.assertIn(("novo", "Novo aparelho: Celular ou tablet .42"), self.eventos())

    def test_mesmo_aparelho_com_outro_ip_mantem_apelido_e_historico(self):
        self.varrer(self.base())
        self.banco.atualizar_dispositivo("mac:f4:7b:09:12:34:56", apelido="TV da sala")
        hosts = self.base()
        hosts["192.168.0.33"] = hosts.pop("192.168.0.21")          # o roteador trocou o IP da TV
        r = self.varrer(hosts)
        self.assertEqual(r["novos"], [])
        tv = self.banco.dispositivo("mac:f4:7b:09:12:34:56")
        self.assertEqual((tv["ip"], tv["apelido"]), ("192.168.0.33", "TV da sala"))

    def test_mac_descoberto_depois_renomeia_sem_perder_o_historico(self):
        hosts = self.base()
        hosts["192.168.0.50"] = host(None, 5.0)                     # ainda sem MAC (fora da tabela ARP)
        self.varrer(hosts)
        self.assertIsNotNone(self.banco.dispositivo("ip:192.168.0.50"))
        self.banco.atualizar_dispositivo("ip:192.168.0.50", apelido="Impressora")
        hosts["192.168.0.50"] = host("64:eb:8c:44:55:66", 5.0)
        self.varrer(hosts)
        self.assertIsNone(self.banco.dispositivo("ip:192.168.0.50"))
        d = self.banco.dispositivo("mac:64:eb:8c:44:55:66")
        self.assertEqual(d["apelido"], "Impressora")
        serie = self.banco.serie("dispositivo:mac:64:eb:8c:44:55:66", 0, self.relogio() + 1, 1)
        self.assertEqual(serie[0][1], 5.0)                          # as duas amostras foram juntas

    def test_saida_so_depois_de_duas_varreduras_e_volta(self):
        self.varrer(self.base())
        sem_tv = {k: v for k, v in self.base().items() if k != "192.168.0.21"}
        self.varrer(sem_tv)
        self.assertTrue(self.banco.dispositivo("mac:f4:7b:09:12:34:56")["online"])   # pode ser só um cochilo
        self.varrer(sem_tv)
        tv = self.banco.dispositivo("mac:f4:7b:09:12:34:56")
        self.assertFalse(tv["online"])
        self.assertEqual(tv["mudou_em"], self.relogio())
        self.varrer(self.base())
        self.assertTrue(self.banco.dispositivo("mac:f4:7b:09:12:34:56")["online"])
        tipos = [t for t, _ in self.eventos()]
        self.assertEqual((tipos.count("saiu"), tipos.count("voltou")), (1, 1))

    def test_aparelho_monitorado_fica_por_conta_do_monitor(self):
        self.varrer(self.base())
        sem_roteador = {k: v for k, v in self.base().items() if k != "192.168.0.1"}
        self.varrer(sem_roteador)
        self.varrer(sem_roteador)
        self.assertTrue(self.banco.dispositivo("mac:a4:2b:b0:11:22:33")["online"])   # o monitor decide
        self.assertNotIn("saiu", [t for t, _ in self.eventos()])

    def test_definir_alertar_prepara_o_monitor(self):
        self.varrer(self.base())
        d = self.inv.definir_alertar("mac:f4:7b:09:12:34:56", True)
        self.assertTrue(d["alertar"])
        trans = self.banco.estado("monitor.transicoes")
        self.assertEqual(trans["dispositivo:mac:f4:7b:09:12:34:56"]["status"], "online")
        self.inv.definir_alertar("mac:f4:7b:09:12:34:56", False)
        self.assertNotIn("dispositivo:mac:f4:7b:09:12:34:56", self.banco.estado("monitor.transicoes"))
        self.assertIsNone(self.inv.definir_alertar("mac:00:00:00:00:00:99", True))

    def test_portas_testadas_de_novo_so_depois_de_6_horas(self):
        self.assertTrue(self.inv.precisa_portas("192.168.0.21", "f4:7b:09:12:34:56"))
        self.varrer(self.base())
        self.assertFalse(self.inv.precisa_portas("192.168.0.21", "f4:7b:09:12:34:56"))
        self.relogio.avancar(minutos=6 * 60 + 1)
        self.assertTrue(self.inv.precisa_portas("192.168.0.21", "f4:7b:09:12:34:56"))
        hosts = self.base()
        hosts["192.168.0.21"]["portas"] = None                     # varredura sem teste de portas
        self.varrer(hosts)
        self.assertEqual(self.banco.dispositivo("mac:f4:7b:09:12:34:56")["portas"], [8008, 8009])


if __name__ == "__main__":
    unittest.main(verbosity=2)
