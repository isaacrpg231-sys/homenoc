"""Integração com o Zabbix contra uma API JSON-RPC simulada."""

import json
import unittest

from apoio import ServidorHTTPFalso, config_e_banco

from homenoc import zabbix

TOKEN = "a" * 64


class ZabbixFalso(ServidorHTTPFalso):
    def __init__(self):
        super().__init__()
        self.token_valido = TOKEN
        self.resposta = self._responder

    def _responder(self, handler):
        pedido = json.loads(self.pedidos[-1]["corpo"])
        metodo, cab = pedido["method"], self.pedidos[-1]["cabecalhos"]
        if metodo == "apiinfo.version":
            if "authorization" in cab:
                return self._erro("Invalid params.", 'The "apiinfo.version" method must be called without '
                                                     'authorization header.')
            return self._ok("7.0.31")
        if cab.get("authorization") != f"Bearer {self.token_valido}":
            return self._erro("Invalid params.", "Session terminated, re-login, please.")
        dados = {
            "host.get": [{"hostid": "1", "name": "Roteador", "interfaces": [{"ip": "192.168.0.1"}]},
                         {"hostid": "2", "name": "Smart TV", "interfaces": [{"ip": "192.168.0.21"}]},
                         {"hostid": "3", "name": "Internet", "interfaces": []}],
            "item.get": [{"hostid": "1", "lastvalue": "1", "lastclock": "1791000000"},
                         {"hostid": "2", "lastvalue": "0", "lastclock": "1791000000"}],
            "problem.get": [{"eventid": "9", "objectid": "77", "name": "ICMP Ping: Unavailable by ICMP ping",
                             "severity": "4", "clock": "1791000100"}],
            "trigger.get": [{"triggerid": "77", "hosts": [{"hostid": "2", "name": "Smart TV"}]}],
        }
        return self._ok(dados[metodo])

    @staticmethod
    def _ok(resultado):
        return json.dumps({"jsonrpc": "2.0", "result": resultado, "id": 1}).encode()

    @staticmethod
    def _erro(msg, dados):
        return json.dumps({"jsonrpc": "2.0", "error": {"code": -32602, "message": msg, "data": dados},
                           "id": 1}).encode()


class ZabbixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ZabbixFalso()
        cls.url = f"{cls.srv.base}/zabbix/api_jsonrpc.php"

    @classmethod
    def tearDownClass(cls):
        cls.srv.fechar()

    def test_resumo_por_ip(self):
        r = zabbix.ZabbixAPI(self.url, TOKEN).resumo()
        self.assertEqual(r["hosts"], 3)
        self.assertEqual(r["por_ip"]["192.168.0.1"], {"nome": "Roteador", "hostid": "1", "ping": True,
                                                      "problemas": []})
        tv = r["por_ip"]["192.168.0.21"]
        self.assertEqual((tv["ping"], tv["problemas"]), (False, ["ICMP Ping: Unavailable by ICMP ping"]))
        self.assertEqual(r["problemas"][0]["gravidade_nome"], "Alta")
        self.assertEqual(r["problemas"][0]["host"], "Smart TV")

    def test_versao_vai_sem_token(self):
        self.assertEqual(zabbix.ZabbixAPI(self.url, TOKEN).versao(), "7.0.31")

    def test_token_errado_vira_mensagem_clara(self):
        r = zabbix.testar(self.url, "b" * 64)
        self.assertFalse(r["ok"])
        self.assertIn("token inválido", r["erro"])

    def test_endereco_errado(self):
        r = zabbix.testar("http://127.0.0.1:9/zabbix/api_jsonrpc.php", TOKEN)
        self.assertFalse(r["ok"])
        self.assertIn("não consegui falar com o Zabbix", r["erro"])

    def test_monitor_atualiza_o_status(self):
        config, _ = config_e_banco()
        m = zabbix.MonitorZabbix(config)
        self.assertFalse(m.configurado())
        config.atualizar({"zabbix": {"url": f"{self.srv.base}/zabbix", "token": TOKEN}})
        m.atualizar()
        self.assertTrue(m.status["ok"])
        self.assertEqual(m.status["versao"], "7.0.31")
        self.assertIn("192.168.0.21", m.status["por_ip"])
        self.assertEqual(zabbix.testar(config.get()["zabbix"]["url"], TOKEN)["problemas"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
