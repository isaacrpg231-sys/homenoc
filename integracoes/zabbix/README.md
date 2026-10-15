# Integração com o Zabbix (opcional)

O HomeNOC já monitora, alerta e mostra o tráfego sozinho. Este guia é para quem quer **também** usar o
[Zabbix](https://www.zabbix.com/), a ferramenta de monitoramento que aparece em muitas vagas de NOC, e ver o que
ele coleta dentro do painel do HomeNOC.

No fim você terá:

- **Zabbix 7.0 LTS** numa VM Debian no notebook, pingando o roteador, a TV e a internet a cada minuto;
- **alerta no Telegram** quando o roteador ou a internet caírem e **"Rede restaurada"** quando voltarem;
- **gráfico do tráfego da internet da casa toda**, com o mesmo script UPnP do HomeNOC;
- o **HomeNOC mostrando os dados do Zabbix**: hosts, ping visto pelo Zabbix e problemas ativos.

Tempo estimado: 1 a 2 horas.

```
integracoes/zabbix/
├── README.md              este guia
└── templates_casa.yaml    templates para importar no Zabbix
homenoc/upnp.py            o script de tráfego (vira upnp_wan.py na VM)
```

> **Onde trocar pelos seus dados:** os comandos marcados com `# EDITE` têm valores de exemplo, como `192.168.1.1` para o roteador, `192.168.1.60` para a VM e `TROQUE_ESTA_SENHA`. Troque pelos seus.

---

## 0. Como tudo se encaixa

```
Internet  (8.8.8.8 e 1.1.1.1 nos testes, api.telegram.org nos alertas)
   │
Roteador 192.168.1.1
   ├── Smart TV
   ├── Celular (Wi-Fi) ............ abre o HomeNOC
   └── Notebook (Windows + VirtualBox)
         ├── HomeNOC ............... painel, mapa, alertas; lê o Zabbix pela API
         └── VM Debian, modo Bridge, IP próprio (ex.: 192.168.1.60)
               ├── Zabbix server ... ping (fping) e tráfego (upnp_wan.py)
               ├── MariaDB ......... guarda o histórico
               └── Apache + PHP .... site e API do Zabbix
```

O que cada um faz, lado a lado:

| HomeNOC | Zabbix |
|---|---|
| ping a cada 1 min nos aparelhos com "Avisar quando cair" | itens ICMP (`icmpping`) a cada 1 min |
| confirma a queda antes de alertar | o gatilho só dispara depois de **3 falhas seguidas** |
| internet fora só se todos os servidores falharem | gatilho "Internet fora do ar" com a mesma regra |
| histórico em SQLite + gráficos no painel | histórico no banco + gráficos |
| Telegram/Discord com fila quando a internet cai | tipo de mídia Telegram, **100 tentativas, 1 por minuto** |
| descobre os aparelhos e desenha o mapa sozinho | hosts cadastrados à mão (ou regras de descoberta) |

**Sobre a ordem das mensagens:** se a internet cai, o Zabbix não consegue falar com o Telegram e fica tentando de novo a cada minuto. Ele só envia o "Rede restaurada" **depois** que a mensagem de queda sair, então elas sempre chegam na ordem certa.

**Uma limitação:** a VM roda no notebook, então o Zabbix só monitora enquanto o notebook estiver ligado. Com ele dormindo, os gráficos ficam com um buraco nesse período, o que é normal.

> **Dica:** se o HomeNOC e o Zabbix mandarem alertas para o mesmo Telegram, você recebe dois avisos por queda. Escolha um para os alertas, ou use um bot diferente para cada.

---

## 1. Preparar a VM no VirtualBox

### 1.1 Criar a VM

| Configuração | Valor |
|---|---|
| Sistema | Debian 12 ou 13, 64 bits |
| Memória | 2048 MB |
| Processadores | 2 |
| Disco | 20 GB |
| **Rede, Adaptador 1** | **Conectado a: Placa em modo Bridge**, Nome: a placa Wi-Fi (ou cabo) do notebook |

O modo Bridge é o ponto principal: ele dá à VM um IP da sua rede, como se fosse mais um aparelho ligado ao roteador. Com isso ela consegue pingar o roteador e a TV, e o HomeNOC consegue falar com ela.

- **NAT** esconde a VM atrás do notebook.
- **Rede Interna** isola a VM da casa. Se for reaproveitar uma VM que já está em Rede Interna, **adicione um Adaptador 2 em modo Bridge** e mantenha o Adaptador 1 como está.

Na instalação do Debian, **não instale ambiente gráfico**. Marque só **"servidor SSH"** e **"utilitários padrão do sistema"**. Assim sobra memória para o Zabbix.

### 1.2 Descobrir e fixar o IP da VM

Na VM, rode `hostname -I` para ver o IP, por exemplo `192.168.1.60`.

Para o IP não mudar (o HomeNOC guarda esse endereço), faça uma **reserva de DHCP** no roteador:

1. No VirtualBox, abra **Configurações → Rede → Avançado** e copie o **Endereço MAC** da VM.
2. Na página do roteador, abra **DHCP → Reserva de endereço** e associe esse MAC a um IP.

### 1.3 Acessar pelo terminal do Windows (recomendado)

Pelo SSH dá para copiar e colar os comandos deste guia. No PowerShell do notebook:

```powershell
ssh seu_usuario@192.168.1.60        # EDITE: usuário e IP da VM
```

> Nos comandos, `sudo` executa como administrador. Se aparecer *"sudo: comando não encontrado"* ou *"não está no arquivo sudoers"*, entre como root com `su -` e rode os comandos sem o `sudo`. Nesse caso, `sudo -u zabbix COMANDO` (passo 5) vira `su -s /bin/sh zabbix -c "COMANDO"`.

### 1.4 Copiar o HomeNOC para a VM

A VM só precisa do script de tráfego, que fica dentro do HomeNOC. No PowerShell, na pasta onde está o projeto:

```powershell
scp .\homenoc\upnp.py seu_usuario@192.168.1.60:~/upnp_wan.py      # EDITE: usuário e IP
```

Os templates (`integracoes/zabbix/templates_casa.yaml`) são importados pelo navegador, direto do notebook (passo 3.4).

---

## 2. Instalar o Zabbix 7.0 LTS

O Zabbix 8.0 ainda está em teste (release candidate), por isso este guia usa a 7.0 LTS, com suporte até 2029.

### 2.1 Pacotes

```bash
sudo timedatectl set-timezone America/Sao_Paulo
sudo apt update
sudo apt install -y wget mariadb-server fping snmp python3

# Repositório oficial do Zabbix 7.0 (no Debian 13, troque debian12 por debian13 nas duas linhas)
wget https://repo.zabbix.com/zabbix/7.0/debian/pool/main/z/zabbix-release/zabbix-release_latest_7.0+debian12_all.deb
sudo dpkg -i zabbix-release_latest_7.0+debian12_all.deb
sudo apt update
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent
```

### 2.2 Banco de dados

```bash
sudo mysql
```

Dentro do MariaDB (troque a senha):

```sql
create database zabbix character set utf8mb4 collate utf8mb4_bin;
create user zabbix@localhost identified by 'TROQUE_ESTA_SENHA';
grant all privileges on zabbix.* to zabbix@localhost;
set global log_bin_trust_function_creators = 1;
quit;
```

Carregue as tabelas do Zabbix. Ele pede a senha que você acabou de criar e leva um ou dois minutos:

```bash
zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz | mysql --default-character-set=utf8mb4 -uzabbix -p zabbix
sudo mysql -e "set global log_bin_trust_function_creators = 0;"
```

### 2.3 Configurar o servidor

Abra o arquivo com `sudo nano /etc/zabbix/zabbix_server.conf` e garanta estas três linhas (sem `#` na frente):

```ini
DBPassword=TROQUE_ESTA_SENHA
FpingLocation=/usr/bin/fping
ExternalScripts=/usr/lib/zabbix/externalscripts
```

- `DBPassword`: troque pela senha que você criou no passo 2.2.
- `FpingLocation`: no Debian, o `fping` fica em `/usr/bin`.
- `ExternalScripts`: a pasta do script de tráfego (passo 5).

> Não escreva comentários no fim dessas linhas. O Zabbix só trata como comentário a linha que começa com `#`; o resto da linha vira parte do valor (e a senha do banco, por exemplo, fica errada).

Depois inicie os serviços:

```bash
sudo mkdir -p /usr/lib/zabbix/externalscripts
sudo systemctl restart zabbix-server zabbix-agent apache2
sudo systemctl enable zabbix-server zabbix-agent apache2
```

### 2.4 Assistente web

No navegador do notebook, abra `http://192.168.1.60/zabbix` (EDITE o IP) e siga o assistente:

1. **Configure DB connection:** tipo MySQL, host `localhost`, banco `zabbix`, usuário `zabbix`, a senha do passo 2.2.
2. **Settings:** nome do servidor `Casa`, fuso `America/Sao_Paulo`.
3. Conclua e entre com **Admin / zabbix**.
4. **Troque a senha do Admin agora:** **User settings → Profile → Change password**.

> Os menus deste guia estão em inglês, o padrão do Zabbix. Se você mudar o idioma para português: *Data collection* = Dados coletados, *Alerts* = Alertas, *Trigger actions* = Ações de trigger, *Latest data* = Dados recentes, *Problems* = Incidentes.

---

## 3. Cadastrar o roteador, a TV e a internet

### 3.1 Grupo

Em **Data collection → Host groups → Create host group**, crie o grupo **`Casa`**. O usuário somente leitura do HomeNOC (passo 6) enxerga só esse grupo.

### 3.2 Roteador

Em **Data collection → Hosts → Create host**:

| Campo | Valor |
|---|---|
| Host name | `Roteador` |
| Templates | `ICMP Ping` |
| Host groups | `Casa` |
| Interfaces | **Add → Agent**, IP `192.168.1.1` (EDITE) |

A interface "Agent" só serve para informar o IP. Não precisa instalar nada no roteador, porque o ping sai do próprio Zabbix.

### 3.3 Smart TV

Faça igual ao roteador, com o nome `Smart TV` e o IP da TV.

A TV some da rede quando entra em standby. Para ela não aparecer como problema toda noite, desative o gatilho dela:

1. Abra **Data collection → Hosts → Smart TV → Triggers**.
2. Marque **"ICMP Ping: Unavailable by ICMP ping"** e clique em **Disable**.

O ping continua sendo gravado e aparece no HomeNOC. É o equivalente a deixar desligado o "Avisar quando cair" da TV no HomeNOC.

> **E o computador?** O notebook é quem roda o Zabbix, então pingar ele mesmo não diz nada. Se tiver outro PC na casa, cadastre como a TV. Se for Windows, libere o ping no firewall desse PC (num terminal como administrador):
> `netsh advfirewall firewall add rule name="Permitir ping da rede local" protocol=icmpv4:8,any dir=in action=allow remoteip=localsubnet`

### 3.4 Importar os templates da casa

1. Abra **Data collection → Templates → Import**.
2. Escolha `integracoes/zabbix/templates_casa.yaml` e clique em **Import**.

Isso cria dois templates:

- **Casa - Internet:** pinga 8.8.8.8 e 1.1.1.1 (macros `{$INTERNET.DNS1}` e `{$INTERNET.DNS2}`) e tem o gatilho **"Internet fora do ar"**, que dispara só quando **os dois** falham 3 vezes seguidas. Inclui o gráfico "Latência da internet".
- **Casa - Tráfego UPnP:** download e upload da casa toda, com o gráfico "Tráfego da internet". Ele só é usado no passo 5.

### 3.5 Host "Internet"

Em **Data collection → Hosts → Create host**: Host name `Internet`, template **`Casa - Internet`**, grupo `Casa`. **Não precisa de interface**, porque os IPs testados já estão nas macros do template.

### 3.6 Dependência: se o roteador cair, avisar só do roteador

Quando o roteador cai, a internet também some. Sem a dependência chegariam dois alertas para o mesmo problema.

1. Abra **Data collection → Hosts → Internet → Triggers → Internet fora do ar**.
2. Na aba **Dependencies**, clique em **Add** e escolha o host **Roteador**, gatilho **"ICMP Ping: Unavailable by ICMP ping"**.
3. Clique em **Update**.

Com a dependência, quando o roteador e a internet caem juntos, o Zabbix manda só o alerta do roteador.

### 3.7 Conferir

Em **Monitoring → Latest data**, filtre pelo grupo `Casa`. Em 1 ou 2 minutos aparecem os valores: `1` no ping significa que respondeu, e a latência fica em segundos (0,013 s = 13 ms). Os gráficos ficam em **Monitoring → Hosts →** (clique no host) **→ Graphs**.

---

## 4. Alertas no Telegram

### 4.1 Bot

Se você já criou o bot para o HomeNOC, use o mesmo token e o mesmo chat_id (eles ficam em Ajustes > Alertas). Se não:

1. No Telegram, fale com o **@BotFather**, envie `/newbot` e guarde o token.
2. Abra a conversa com o seu bot e envie `/start`.
3. Para descobrir o chat_id, use o botão **Descobrir meu chat_id** do HomeNOC (Ajustes > Alertas) ou abra `https://api.telegram.org/bot<TOKEN>/getUpdates` no navegador e procure `"chat":{"id":123456789`.

### 4.2 Tipo de mídia

Em **Alerts → Media types**, clique em **Telegram**:

- **Aba Media type:** em *Parameters*, troque o valor de `api_token` (`<PLACE YOUR TOKEN>`) pelo token do bot. Deixe `api_parse_mode` como está, para texto simples.
- Marque **Enabled**.
- **Aba Options:** *Attempts* = `100`, *Attempt interval* = `1m`. É a "fila" para quando a internet cair: ele tenta por até 1 h 40 min.
- Clique em **Update**.

### 4.3 Para quem enviar

1. Abra **Users → Users → Admin → aba Media → Add**.
2. Em *Type*, escolha `Telegram`. Em *Send to*, coloque o seu chat_id.
3. Clique em **Add** e depois em **Update**.

### 4.4 Ação: quando enviar

Em **Alerts → Actions → Trigger actions → Create action**, preencha as duas abas (*Action* e *Operations*).

**Aba Action**
- *Name*: `Alertas da rede de casa`.
- *Conditions*, adicione três:
  - *Host* **equals** `Roteador`
  - *Host* **equals** `Internet`
  - *Trigger severity* **is greater than or equals** `High`
- O Zabbix combina assim: (Roteador **ou** Internet) **e** gravidade alta. Avisos menores, como "latência alta", não mandam mensagem.

**Aba Operations → Operations → Add**
- *Send to users*: `Admin`. *Send to media type*: `Telegram`.
- Marque **Custom message**:
  - *Subject*: `🔴 {HOST.NAME} FORA DO AR`
  - *Message*:
    ```
    Detalhe: {EVENT.NAME}
    Desde: {EVENT.TIME} ({EVENT.DATE})
    ```

**Aba Operations → Recovery operations → Add**
- *Operation*: **Notify all involved**.
- Marque **Custom message**:
  - *Subject*: `🟢 REDE RESTAURADA: {HOST.NAME}`
  - *Message*:
    ```
    Ficou fora por {EVENT.DURATION}.
    Voltou às {EVENT.RECOVERY.TIME} ({EVENT.RECOVERY.DATE})
    ```

Clique em **Add** para salvar a ação. O teste está no passo 7.

---

## 5. Tráfego da internet da casa toda

O tráfego da casa inteira passa pelo roteador, então é dele que vêm os números. Existem dois jeitos de ler, e depende do que o seu roteador suporta. Teste nesta ordem.

### 5.1 Teste UPnP (funciona na maioria dos roteadores domésticos)

```bash
sudo cp ~/upnp_wan.py /usr/lib/zabbix/externalscripts/upnp_wan.py
sudo chmod 755 /usr/lib/zabbix/externalscripts/upnp_wan.py
sudo -u zabbix python3 /usr/lib/zabbix/externalscripts/upnp_wan.py --testar
```

É o mesmo `homenoc/upnp.py` que o HomeNOC usa: sozinho, ele funciona como "verificação externa" do Zabbix.

Se aparecer algo assim, o seu roteador suporta:

```
Procurando o roteador via UPnP...
[OK] Roteador: (nome do seu roteador)
[OK] Contadores atuais: 2,77 GB recebidos, 2,02 GB enviados
     Medindo a velocidade por 5 segundos...
[OK] Download agora: 49,91 Mbps | Upload agora: 5,22 Mbps
Tudo certo: dá para usar este script no Zabbix (passo 5 do guia).
```

Agora ligue o template ao host:

1. Abra **Data collection → Hosts → Internet** e, no campo *Templates*, adicione **`Casa - Tráfego UPnP`**.
2. Clique em **Update**.

O tráfego é lido a cada 30 s. Veja em **Monitoring → Hosts → Internet → Graphs → Tráfego da internet**.

Se der **"nenhum roteador respondeu ao UPnP"**, procure **UPnP** na página do roteador (menus NAT, Avançado ou Rede), ative e teste de novo. Se mesmo assim não der, vá para o 5.2.

> **Por que o primeiro valor demora:** o roteador informa o **total de bytes** desde que ligou. O Zabbix calcula a velocidade pela diferença entre duas leituras (*Change per second* × 8 = bits por segundo). Muitos roteadores usam contador de 32 bits, que "dá a volta" a cada 4 GB. Quando isso acontece, o Zabbix descarta aquela leitura em vez de desenhar um pico falso. Isso foi conferido no código e no teste.

### 5.2 Teste SNMP (roteadores mais completos, MikroTik, OpenWrt)

```bash
snmpwalk -v2c -c public 192.168.1.1 1.3.6.1.2.1.1.1      # EDITE o IP
```

Se responder com a descrição do roteador, mude o host Roteador:

1. Na aba *Interfaces*, clique em **Add → SNMP**, com o IP do roteador e SNMPv2.
2. Em *Templates*, **remova** `ICMP Ping` (*Unlink and clear*) e adicione **`Network Generic Device by SNMP`**. Esse template já inclui o ping; os dois juntos dão conflito.
3. Para descobrir as interfaces na hora, abra **Discovery → Network interfaces discovery** e clique em **Execute now**.
4. Os itens **"Interface ...: Bits received/sent"** aparecem. A interface WAN costuma se chamar `ppp0`, `wan`, `nas0` ou `eth0.2`.
5. Refaça a dependência do passo 3.6 apontando para **"Network Generic Device: Unavailable by ICMP ping"**.

### 5.3 Nenhum dos dois funcionou?

Roteadores de operadora às vezes bloqueiam tudo. As saídas são:

- usar um roteador próprio com SNMP ou OpenWrt atrás do modem;
- colocar um switch gerenciável com SNMP entre o modem e o roteador e monitorar a porta do roteador.

O resto do guia (ping, alertas e a ligação com o HomeNOC) funciona sem o tráfego.

### 5.4 Dashboard no notebook (opcional)

1. Abra **Dashboards → Create dashboard** e dê o nome `Casa`.
2. Clique em **Add widget** e escolha **Graph (classic)**, com o gráfico *Internet: Tráfego da internet*.
3. Adicione também um widget **Problems** e salve.

---

## 6. Mostrar o Zabbix no HomeNOC

O HomeNOC lê o Zabbix pela API com um usuário que **só pode ler**. Assim, mesmo que alguém pegue o token, não dá
para mudar nada no Zabbix.

### 6.1 Usuário somente leitura

1. **Users → User roles → Create user role**
   - *Name*: `HomeNOC leitura`. *User type*: `User`.
   - *API access*: **Enabled**. *API methods*: **Allow list**, com estes quatro:
     `host.get` `item.get` `problem.get` `trigger.get`
2. **Users → User groups → Create user group**
   - *Name*: `HomeNOC leitura`. *Frontend access*: **Disabled** (o usuário não entra no site, só usa a API).
   - Aba *Host permissions*: grupo `Casa`, permissão **Read**.
3. **Users → Users → Create user**
   - *Username*: `homenoc`. *Groups*: `HomeNOC leitura`.
   - *Password*: no mínimo 8 caracteres e **sem conter "homenoc"**, ou o Zabbix recusa.
   - Aba *Permissions*: *Role* `HomeNOC leitura`.
4. **Users → API tokens → Create API token**
   - *Name*: `HomeNOC`. *User*: `homenoc`. Desmarque *Set expiration date and time*.
   - Clique em **Add** e **copie o token**: ele só aparece uma vez.

### 6.2 Ligar no HomeNOC

1. No HomeNOC, abra **Ajustes → Zabbix**.
2. *Endereço do Zabbix*: `http://192.168.1.60/zabbix` (EDITE o IP da VM; o final `/api_jsonrpc.php` é completado sozinho).
3. *Token da API*: cole o token do passo 6.1.
4. Clique em **Testar conexão**. O esperado é *"Funcionou: Zabbix 7.0.x, 3 hosts, 0 problemas ativos."*
5. Clique em **Salvar Zabbix**.

O que aparece no HomeNOC:

- o LED **Zabbix** no painel, com o número de hosts;
- na gaveta de cada aparelho que também está no Zabbix (o HomeNOC liga os dois pelo IP): o nome no Zabbix, o ping visto pelo Zabbix e os problemas ativos;
- problemas de gravidade **Alta** ou **Desastre** viram o aviso principal do painel.

O HomeNOC consulta o Zabbix a cada minuto. Se a VM estiver desligada, o LED fica amarelo ("sem conexão") e o resto do HomeNOC continua normal.

---

## 7. Testar tudo

**Queda do roteador, sem desligar nada:**

1. Em **Data collection → Hosts → Roteador → Interfaces**, troque o IP por um que ninguém usa, como `192.168.1.254`, e salve.
2. Em cerca de 3 minutos (3 falhas seguidas) chega no Telegram:
   ```
   🔴 Roteador FORA DO AR
   Detalhe: ICMP Ping: Unavailable by ICMP ping
   Desde: 20:55:51 (2026.10.06)
   ```
3. Volte o IP certo. No minuto seguinte chega a resposta, encadeada na mensagem de queda:
   ```
   🟢 REDE RESTAURADA: Roteador
   Ficou fora por 1m 10s.
   Voltou às 20:57:01 (2026.10.06)
   ```

**Queda real da internet:** tire o cabo da fibra (WAN) do roteador por uns 5 minutos.

- O HomeNOC mostra "Internet fora do ar" na hora, porque roda na rede local.
- As mensagens do Telegram chegam quando você recolocar o cabo, primeiro a queda e depois a restauração.

Para conferir cada envio e o erro de cada tentativa, use **Reports → Action log**.

---

## 8. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `http://IP/zabbix` não abre | VM sem IP da rede | Confira o modo Bridge e rode `hostname -I` na VM |
| Itens de ping "Not supported", erro de fping | caminho do fping | `FpingLocation=/usr/bin/fping` no passo 2.3 e `sudo systemctl restart zabbix-server` |
| Tudo aparece fora, mas a internet do notebook funciona | o Bridge pelo Wi-Fi não pegou | Teste `ping 192.168.1.1` dentro da VM; troque a placa escolhida no Bridge ou use cabo |
| Telegram não chega | token, chat_id ou faltou `/start` | **Reports → Action log** mostra o erro (*Unauthorized* = token; *chat not found* = chat_id ou `/start`) |
| Tráfego "Not supported" | script ou UPnP | `sudo -u zabbix /usr/lib/zabbix/externalscripts/upnp_wan.py recebidos` mostra o erro em português |
| HomeNOC: "token inválido ou expirado" | token errado ou apagado | Gere outro em **Users → API tokens** e cole em Ajustes > Zabbix |
| HomeNOC: "não consegui falar com o Zabbix" | VM desligada ou IP mudou | Ligue a VM e confira o IP (reserva de DHCP do passo 1.2) |
| HomeNOC: "o usuário do token não pode chamar ..." | método fora da lista do papel | Revise a *Allow list* do passo 6.1 |
| Gráficos com buracos | o notebook dormiu | É normal: o Zabbix só coleta com a VM ligada |

> **Se o Bridge pelo Wi-Fi não funcionar de jeito nenhum** (acontece com alguns adaptadores), use NAT. O ping para a rede de casa costuma funcionar pelo NAT do VirtualBox. Crie um redirecionamento de porta 8080 → 80 em **Rede → Avançado → Redirecionamento de portas** e use `http://127.0.0.1:8080/zabbix` no HomeNOC.

---

## Como foi testado

Este guia foi montado com apoio de IA, num ambiente Linux de desenvolvimento. Nesse ambiente:

- os templates (`templates_casa.yaml`) foram importados num **Zabbix 7.0.31** compilado do código oficial, com PostgreSQL, e os passos 3 a 5 e 7 foram conferidos nele com um roteador UPnP e um Telegram **simulados** (incluindo o contador de 32 bits dando a volta e a dependência do passo 3.6);
- no passo 6, os métodos que o HomeNOC usa (`host.get`, `item.get`, `problem.get`, `trigger.get` e `apiinfo.version`) foram chamados nesse Zabbix com um token somente leitura;
- o código do HomeNOC que faz essas chamadas (`homenoc/zabbix.py`) foi testado só contra uma API simulada, em `tests/test_zabbix.py`.

Ainda **não** foi testado:

- os passos 1 e 2 como estão escritos (VM no VirtualBox, pacotes do Debian com MariaDB);
- o Bridge pelo Wi-Fi de um notebook de verdade;
- um roteador de verdade: rode o `--testar` do passo 5 no seu;
- o envio para o Telegram de verdade (o tipo de mídia usado é o oficial do Zabbix);
- o HomeNOC ligado a um Zabbix de verdade (o passo 6 de ponta a ponta).
